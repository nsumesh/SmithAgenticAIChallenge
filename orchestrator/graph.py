"""
Advanced orchestration agent -- LangGraph StateGraph.

Graph topology (plan-first HITL):
  interpret → plan → reflect → [revise] → approval_gate
                                            ├── LOW/MEDIUM: execute → observe → [re-plan?] → output
                                            └── HIGH/CRITICAL: output (plan-only, awaiting human)

  After human approves: run_orchestrator_selective() does the real execution.

The approval gate ensures tools only run ONCE — after human review for
HIGH/CRITICAL events. LOW/MEDIUM events execute automatically.
"""

from __future__ import annotations

import logging
import os
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

MAX_REPLAN = 1


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
    """Deterministic post-execution check: flag if critical tools failed."""
    tool_results = state.get("tool_results", [])
    tier = state.get("risk_input", {}).get("risk_tier", "LOW")
    failed = [r["tool"] for r in tool_results if not r.get("success")]

    if failed and tier == "CRITICAL":
        return {
            "observation": f"CRITICAL: {len(failed)} tools failed: {failed}",
            "needs_replan": True,
            "observation_issues": [f"{t} failed" for t in failed],
            "observation_actions": [f"retry or replace {t}" for t in failed],
        }
    return {"observation": "adequate", "needs_replan": False}


def _should_revise(state: OrchestratorState) -> str:
    notes = state.get("reflection_notes", [])
    tier = state["risk_input"].get("risk_tier", "LOW")

    if tier == "LOW":
        return "skip_to_output"

    has_gaps = any("GAP" in str(n).upper() for n in notes)
    already_revised = state.get("plan_revised", False)

    if has_gaps and not already_revised:
        return "revise"
    return "approval_gate"


def _approval_gate(state: OrchestratorState) -> dict:
    """Decide whether to pause for human approval or auto-execute.

    HIGH/CRITICAL → creates an approval request and STOPS (no tool execution).
    MEDIUM → proceeds to execute automatically.
    """
    tier = state["risk_input"].get("risk_tier", "MEDIUM")
    requires = tier in ("HIGH", "CRITICAL")

    if requires:
        from tools.approval_workflow import _execute as create_approval
        ri = state["risk_input"]
        active = state.get("active_plan") or state.get("draft_plan", [])
        proposed = [s.get("tool", "") for s in active if isinstance(s, dict) and s.get("tool") != "approval_workflow"]

        result = create_approval(
            shipment_id=ri.get("shipment_id", ""),
            action_description=f"{tier} risk event: {state.get('primary_issue', 'unknown')}",
            risk_tier=tier,
            urgency="immediate" if tier == "CRITICAL" else "urgent",
            proposed_actions=proposed,
            justification=state.get("llm_reasoning", "Agentic plan requires human review"),
            requested_by="orchestrator",
            window_id=ri.get("window_id"),
            container_id=ri.get("container_id"),
        )
        logger.info("APPROVAL_GATE  tier=%s → paused, approval_id=%s, proposed=%s",
                     tier, result.get("approval_id"), proposed)
        return {
            "requires_approval": True,
            "approval_reason": f"{tier} risk requires human review before tool execution",
            "approval_id": result.get("approval_id"),
            "awaiting_approval": True,
        }
    else:
        return {
            "requires_approval": False,
            "awaiting_approval": False,
        }


def _after_approval_gate(state: OrchestratorState) -> str:
    """Route after the approval gate: execute or stop."""
    if state.get("awaiting_approval"):
        return "plan_only_output"
    return "execute"


def _should_replan(state: OrchestratorState) -> str:
    """After observe: re-plan if needed and under the iteration limit."""
    needs = state.get("needs_replan", False)
    count = state.get("replan_count", 0)

    if needs and count < MAX_REPLAN:
        logger.info("OBSERVE→REPLAN: iteration %d, re-planning", count + 1)
        return "replan"
    return "finalize"


def _replan_increment(state: OrchestratorState) -> dict:
    """Bump the replan counter and feed observation back into planning context."""
    count = state.get("replan_count", 0)
    issues = state.get("observation_issues", [])
    obs = state.get("observation", "")

    existing_notes = state.get("reflection_notes", [])
    new_notes = list(existing_notes) + [f"OBSERVATION: {obs}"] + [f"ISSUE: {i}" for i in issues]

    return {
        "replan_count": count + 1,
        "plan_revised": False,
        "reflection_notes": new_notes,
    }


def build_orchestrator() -> StateGraph:
    """Construct the orchestration StateGraph with plan-first HITL.

    Topology:
      interpret → plan → reflect ─┬─ GAP → revise → approval_gate
                                   ├─ OK  → approval_gate
                                   └─ LOW → output (skip)
      approval_gate ─┬─ HIGH/CRITICAL → output (plan-only, awaiting approval)
                     └─ MEDIUM       → execute → observe → [replan?] → output
    """
    graph = StateGraph(OrchestratorState)

    plan_node = _get_plan_node()
    reflect_node = _get_reflect_node()
    revise_node = _get_revise_node()
    observe_node = _get_observe_node()

    graph.add_node("interpret", interpret_risk)
    graph.add_node("plan", plan_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("revise", revise_node)
    graph.add_node("approval_gate", _approval_gate)
    graph.add_node("execute", execute)
    graph.add_node("observe", observe_node)
    graph.add_node("replan_bridge", _replan_increment)
    graph.add_node("fallback", build_fallback)
    graph.add_node("output", compile_output)

    graph.set_entry_point("interpret")
    graph.add_edge("interpret", "plan")
    graph.add_edge("plan", "reflect")

    graph.add_conditional_edges(
        "reflect",
        _should_revise,
        {"revise": "revise", "approval_gate": "approval_gate", "skip_to_output": "output"},
    )

    graph.add_edge("revise", "approval_gate")

    graph.add_conditional_edges(
        "approval_gate",
        _after_approval_gate,
        {"execute": "execute", "plan_only_output": "output"},
    )

    graph.add_edge("execute", "observe")

    graph.add_conditional_edges(
        "observe",
        _should_replan,
        {"replan": "replan_bridge", "finalize": "fallback"},
    )

    graph.add_edge("replan_bridge", "plan")
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
    """Execute only the human-selected tools — bypasses plan/reflect/revise.

    Directly runs: interpret → build plan → execute → observe → compile.
    Does NOT go through the LangGraph to avoid the LLM overwriting the
    human-selected plan.
    """
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
        "reflection_notes": ["Human-selected tools — skipping plan/reflect/revise."],
        "llm_reasoning": "Plan constructed by human operator via tool selection UI.",
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


# Re-export TOOL_MAP for the selective runner
from tools import TOOL_MAP
