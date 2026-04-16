"""
Advanced orchestration agent -- LangGraph StateGraph.

Topology (act-first, HITL always-review):
  interpret -> plan -> [tier_route]
    LOW  -> output  (monitoring only)
    MEDIUM+ -> execute -> observe -> reflect -> [should_revise]
        adequate  -> human_review -> output
        has gaps  -> revise -> human_review -> output

Every MEDIUM+ event pauses at human_review.  The human can:
  - Confirm (first pass was sufficient)
  - Approve corrective tools (execute them)
  - Modify the corrective selection
  - Dismiss corrections and close with first-pass results

Re-execution only happens via the POST /api/approvals/{id}/execute
endpoint, outside the graph.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from orchestrator.llm_provider import get_llm, get_provider_name, get_model_name
from orchestrator.nodes import (
    build_fallback,
    compile_output,
    execute,
    interpret_risk,
    plan as plan_deterministic,
    reflect as reflect_deterministic,
    revise as revise_deterministic,
)
from orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)


def _get_plan_node():
    if get_llm() is not None:
        from orchestrator.llm_nodes import plan_llm
        logger.info("Plan node: AGENTIC (%s/%s)", get_provider_name(), get_model_name())
        return plan_llm
    logger.info("Plan node: DETERMINISTIC (no LLM available)")
    return plan_deterministic


def _get_reflect_node():
    if get_llm() is not None:
        from orchestrator.llm_nodes import reflect_llm
        logger.info("Reflect node: AGENTIC (%s/%s)", get_provider_name(), get_model_name())
        return reflect_llm
    logger.info("Reflect node: DETERMINISTIC")
    return reflect_deterministic


def _get_revise_node():
    if get_llm() is not None:
        from orchestrator.llm_nodes import revise_llm
        logger.info("Revise node: AGENTIC (%s/%s)", get_provider_name(), get_model_name())
        return revise_llm
    logger.info("Revise node: DETERMINISTIC")
    return revise_deterministic


def _get_observe_node():
    if get_llm() is not None:
        from orchestrator.llm_nodes import observe_llm
        logger.info("Observe node: AGENTIC (%s/%s)", get_provider_name(), get_model_name())
        return observe_llm
    return _observe_deterministic


def _observe_deterministic(state: OrchestratorState) -> dict:
    """Deterministic post-execution summary."""
    tool_results = state.get("tool_results", [])
    failed = [r["tool"] for r in tool_results if not r.get("success")]
    return {
        "observation": f"{len(tool_results)} tools ran, {len(failed)} failed"
                       if tool_results else "no tools executed",
    }


# ── Conditional routing ──────────────────────────────────────────────

def _skip_if_low(state: OrchestratorState) -> str:
    tier = state["risk_input"].get("risk_tier", "LOW")
    if tier == "LOW":
        return "output"
    return "execute"


def _should_revise(state: OrchestratorState) -> str:
    """After reflect: always revise (notification is always deferred)."""
    return "revise"


# ── Human review node ────────────────────────────────────────────────

def _human_review(state: OrchestratorState) -> dict:
    """Always-fire review gate for MEDIUM+ events.

    The revised plan always contains at least notification_agent (deferred from
    first-pass execution).  It may also contain corrective tools identified by
    reflect+revise.

    The human can:
      - Approve all proposed actions (corrections + notification)
      - Deselect individual tools
      - Dismiss corrections but still approve notification
    """
    from tools.approval_workflow import _execute as create_approval
    ri = state["risk_input"]
    tier = ri.get("risk_tier", "MEDIUM")
    deferred = set(state.get("deferred_tools", []))

    tool_results = state.get("tool_results", [])
    first_pass_tools = [r["tool"] for r in tool_results]
    succeeded = [r["tool"] for r in tool_results if r.get("success")]
    failed = [r["tool"] for r in tool_results if not r.get("success")]

    revised_plan = state.get("revised_plan", [])
    proposed_all = [
        s.get("tool", "") for s in revised_plan
        if isinstance(s, dict) and s.get("tool") != "approval_workflow"
    ]
    proposed_corrections = [t for t in proposed_all if t not in deferred]
    proposed_deferred = [t for t in proposed_all if t in deferred]

    has_corrections = bool(proposed_corrections)

    if has_corrections:
        description = (
            f"{tier} risk: executed {len(first_pass_tools)} tools "
            f"({len(succeeded)} OK, {len(failed)} failed). "
            f"Reflection identified {len(proposed_corrections)} corrective action(s): "
            f"{', '.join(proposed_corrections)}. "
            f"Notification pending approval."
        )
        review_status = "corrections_proposed"
    else:
        description = (
            f"{tier} risk: executed {len(first_pass_tools)} tools "
            f"({len(succeeded)} OK, {len(failed)} failed). "
            f"No corrective actions needed — notification pending approval."
        )
        review_status = "notification_pending"

    all_available = list(TOOL_MAP.keys())
    remaining_tools = [t for t in all_available
                       if t not in succeeded and t != "approval_workflow"
                       and t not in proposed_all]
    proposed_actions = proposed_all + remaining_tools

    result = create_approval(
        shipment_id=ri.get("shipment_id", ""),
        action_description=description,
        risk_tier=tier,
        urgency="immediate" if tier == "CRITICAL" else (
            "urgent" if tier == "HIGH" else "standard"
        ),
        proposed_actions=proposed_actions,
        justification=state.get("llm_reasoning", "Post-execution review required"),
        requested_by="orchestrator",
        window_id=ri.get("window_id"),
        container_id=ri.get("container_id"),
    )

    first_pass_actions = [
        {"tool": r["tool"], "input": r.get("input", {}), "result": r.get("result", {}), "_pass": "first_pass"}
        for r in tool_results
    ]

    def _steps_to_dicts(steps):
        return [{"step": s.get("step", i+1), "action": s.get("action", ""), "reason": s.get("reason", ""),
                 "tool": s.get("tool", "")}
                for i, s in enumerate(steps or []) if isinstance(s, dict)]

    from tools.approval_workflow import _PENDING_APPROVALS
    aid = result.get("approval_id")
    if aid and aid in _PENDING_APPROVALS:
        _PENDING_APPROVALS[aid]["review_status"] = review_status
        _PENDING_APPROVALS[aid]["proposed_corrections"] = proposed_corrections
        _PENDING_APPROVALS[aid]["proposed_deferred"] = proposed_deferred
        _PENDING_APPROVALS[aid]["first_pass_tools"] = first_pass_tools
        _PENDING_APPROVALS[aid]["first_pass_actions"] = first_pass_actions
        _PENDING_APPROVALS[aid]["cascade_context"] = state.get("cascade_context", {})
        _PENDING_APPROVALS[aid]["original_plan"] = {
            "draft_plan": _steps_to_dicts(state.get("draft_plan")),
            "reflection_notes": state.get("reflection_notes", []),
            "revised_plan": _steps_to_dicts(state.get("revised_plan")),
            "llm_reasoning": state.get("llm_reasoning", ""),
            "observation": state.get("observation", ""),
            "observation_issues": state.get("observation_issues", []),
            "observation_actions": state.get("observation_actions", []),
            "proposed_tools": [s.get("tool", "") for s in (state.get("revised_plan") or [])
                               if isinstance(s, dict) and s.get("tool") != "approval_workflow"],
            "decision_summary": state.get("decision_summary", ""),
            "confidence": state.get("confidence", 0),
        }

    logger.info(
        "HUMAN_REVIEW  tier=%s review_status=%s first_pass=%d corrections=%d deferred=%d id=%s",
        tier, review_status, len(first_pass_tools), len(proposed_corrections),
        len(proposed_deferred), result.get("approval_id"),
    )
    return {
        "requires_approval": True,
        "awaiting_approval": True,
        "approval_reason": description,
        "approval_id": result.get("approval_id"),
        "review_status": review_status,
    }


# ── Build graph ──────────────────────────────────────────────────────

def build_orchestrator() -> StateGraph:
    """Construct the act-first, always-review orchestration graph.

    Plan -> Execute -> Observe -> Reflect -> [Revise] -> Human Review -> Output
    """
    graph = StateGraph(OrchestratorState)

    plan_node = _get_plan_node()
    reflect_node = _get_reflect_node()
    revise_node = _get_revise_node()
    observe_node = _get_observe_node()

    graph.add_node("interpret", interpret_risk)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute)
    graph.add_node("observe", observe_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("revise", revise_node)
    graph.add_node("human_review", _human_review)
    graph.add_node("fallback", build_fallback)
    graph.add_node("output", compile_output)

    graph.set_entry_point("interpret")
    graph.add_edge("interpret", "plan")

    graph.add_conditional_edges(
        "plan",
        _skip_if_low,
        {"output": "output", "execute": "execute"},
    )

    graph.add_edge("execute", "observe")
    graph.add_edge("observe", "reflect")

    graph.add_conditional_edges(
        "reflect",
        _should_revise,
        {"revise": "revise", "human_review": "human_review"},
    )

    graph.add_edge("revise", "human_review")
    graph.add_edge("human_review", "fallback")
    graph.add_edge("fallback", "output")
    graph.add_edge("output", END)

    return graph


_compiled = None
_last_provider = None


def get_compiled():
    global _compiled, _last_provider
    current = get_provider_name()
    if _compiled is None or current != _last_provider:
        _compiled = build_orchestrator().compile()
        _last_provider = current
    return _compiled


def run_orchestrator(risk_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run the orchestration agent on a single risk engine output."""
    app = get_compiled()
    initial: OrchestratorState = {"risk_input": risk_input, "replan_count": 0}
    final_state = app.invoke(initial)
    return final_state.get("final_output", {})


def run_orchestrator_selective(
    risk_input: Dict[str, Any],
    selected_tools: list[str],
) -> Dict[str, Any]:
    """Execute only the human-selected tools -- bypasses plan/reflect/revise."""
    from orchestrator.nodes import (
        interpret_risk, execute, build_fallback, compile_output, _build_tool_input,
    )
    from orchestrator.state import PlanStep

    plan_steps = []
    for i, tool_name in enumerate(selected_tools, 1):
        if tool_name in TOOL_MAP:
            plan_steps.append(PlanStep(
                step=i, action=f"Execute {tool_name} (human-selected)",
                tool=tool_name,
                tool_input=_build_tool_input(tool_name, risk_input, {"risk_input": risk_input}),
                reason="Selected by human operator",
            ))

    state: OrchestratorState = {
        "risk_input": risk_input,
        "replan_count": 0,
        "draft_plan": plan_steps,
        "active_plan": plan_steps,
        "plan_revised": True,
        "reflection_notes": ["Human-selected tools."],
        "llm_reasoning": "Plan constructed by human operator via tool selection UI.",
        "deferred_tools": [],
    }

    state.update(interpret_risk(state))
    state.update(execute(state))

    observe_node = _get_observe_node()
    state.update(observe_node(state))

    state.update(build_fallback(state))
    state.update(compile_output(state))

    return state.get("final_output", {})


def get_graph_mermaid() -> str:
    graph = build_orchestrator()
    return graph.compile().get_graph().draw_mermaid()


def get_mode() -> Dict[str, str]:
    return {
        "mode": "agentic" if get_llm() is not None else "deterministic",
        "provider": get_provider_name(),
        "model": get_model_name(),
    }


from tools import TOOL_MAP
