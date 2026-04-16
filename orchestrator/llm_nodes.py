"""
LLM-powered agentic nodes for the orchestration graph.

These are TRUE agentic nodes: the LLM reasons about the situation, decides
which tools to call, AND constructs the tool input payloads itself.

The deterministic _build_tool_input() is only used as a safety net when the
LLM produces malformed inputs -- it does NOT drive the agent's decisions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from orchestrator.llm_provider import get_llm
from orchestrator.state import OrchestratorState, PlanStep, ToolResult
from tools import TOOL_MAP

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response that may contain markdown fences."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find balanced outermost braces instead of greedy first-to-last match
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    return {}


TOOL_SCHEMAS = {}
for _name, _tool in TOOL_MAP.items():
    schema = _tool.args_schema.model_json_schema() if _tool.args_schema else {}
    props = schema.get("properties", {})
    required = schema.get("required", [])
    req_fields = [f for f in required if f in props]
    fields = []
    for fname in req_fields:
        finfo = props[fname]
        ftype = finfo.get("type", "string")
        fields.append(f"{fname}:{ftype}")
    TOOL_SCHEMAS[_name] = f"  {_name}({', '.join(fields)})"

TOOLS_REFERENCE = "\n".join(TOOL_SCHEMAS.values())


# ── Agentic Plan ─────────────────────────────────────────────────────

PLAN_SYSTEM = """You are an expert pharmaceutical cold-chain orchestration agent. You make autonomous decisions about shipment interventions based on GDP (Good Distribution Practice), FDA 21 CFR Part 211, and WHO PQS guidelines.

DOMAIN KNOWLEDGE:
- Temperature excursions degrade biologics exponentially, not linearly. A 2°C overshoot for 60 min is NOT equivalent to 1°C for 120 min.
- Cumulative excursion budget (related to Mean Kinetic Temperature) is the key metric. Once exceeded, product is suspect regardless of current temperature.
- Frozen products (-20°C) can tolerate brief warming but NEVER refreezing. Refrigerated products (2-8°C) can tolerate brief 0-12°C excursions.
- Delay + temperature stress is a compound risk: cooling systems degrade under extended operation, making breach more likely over time.
- Compliance logging MUST happen BEFORE any intervention (audit trail integrity per GDP Chapter 9).
- Downstream healthcare facilities need advance notice for appointment rescheduling -- patient impact is the ultimate consequence.

DECISION RULES:
- CRITICAL: compliance_agent FIRST (audit trail), then cold_storage_agent (temp recovery), notification_agent (stakeholder alert), insurance_agent (financial protection), scheduling_agent (patient impact), approval_workflow LAST (human sign-off on irreversible actions).
- HIGH: compliance_agent FIRST, notification_agent, scheduling_agent if delay_class is developing/critical, approval_workflow LAST.
- MEDIUM: compliance_agent, notification_agent. No approval needed.
- LOW: empty steps. Monitoring only.
- Construct tool inputs using the actual shipment data. Do NOT use placeholder values.
- Return ONLY valid JSON."""


def plan_llm(state: OrchestratorState) -> dict:
    """LLM agent generates plan with tool names AND tool input payloads."""
    llm = get_llm()
    if llm is None:
        from orchestrator.nodes import plan as det_plan
        return det_plan(state)

    ri = state["risk_input"]

    facility = ri.get("facility", {})
    cost = ri.get("product_cost", {})
    context_block = f"""
  delay_class: {ri.get('delay_class', 'unknown')}
  delay_ratio: {ri.get('delay_ratio', 'N/A')}
  hours_to_breach: {ri.get('hours_to_breach', 'N/A')}
  current_delay_min: {ri.get('current_delay_min', 0)}
  facility_name: {facility.get('name', 'unknown')}
  facility_location: {facility.get('location', 'unknown')}
  shipment_value_usd: {cost.get('shipment_value_usd', 'N/A')}
  product_name: {cost.get('product_name', ri.get('product_type', ''))}"""

    # Derive domain context the LLM needs to reason about
    delay_class = ri.get('delay_class', 'unknown')
    hours_breach = ri.get('hours_to_breach')
    breach_urgency = "ALREADY BREACHED" if hours_breach == 0.0 else (
        f"~{hours_breach:.1f}h until breach" if hours_breach else "stable"
    )
    spoilage = ri.get('ml_spoilage_probability', 0)
    spoilage_risk = "very high (>80%)" if spoilage > 0.8 else (
        "high (>50%)" if spoilage > 0.5 else "moderate" if spoilage > 0.2 else "low"
    )

    user_msg = f"""Analyze this risk event and create an action plan.

RISK EVENT:
  shipment_id: {ri.get('shipment_id')}
  container_id: {ri.get('container_id')}
  window_id: {ri.get('window_id')}
  leg_id: {ri.get('leg_id')}
  product_type: {ri.get('product_type')}
  transit_phase: {ri.get('transit_phase')}
  risk_tier: {ri.get('risk_tier')}
  fused_risk_score: {ri.get('fused_risk_score')}
  ml_spoilage_probability: {spoilage} ({spoilage_risk})
  deterministic_rule_flags: {ri.get('deterministic_rule_flags', [])}
  severity: {state.get('severity', 'unknown')}
  primary_issue: {state.get('primary_issue', '')}
{context_block}

DOMAIN ANALYSIS:
  excursion_budget_status: {delay_class} (delay_ratio={ri.get('delay_ratio', 'N/A')})
  breach_timeline: {breach_urgency}
  compound_risk: {"YES - delay + temperature stress" if 'delay_temp_stress' in ri.get('deterministic_rule_flags', []) else "no compound risk detected"}

AVAILABLE TOOLS (with input schemas):
{TOOLS_REFERENCE}

Respond with ONLY this JSON:
{{
  "reasoning": "2-3 sentences analyzing what this specific situation needs based on the domain context",
  "steps": [
    {{
      "step": 1,
      "action": "what this step does",
      "tool": "tool_name",
      "tool_input": {{...actual input fields for this tool...}},
      "reason": "why this step is needed"
    }}
  ],
  "requires_approval": true,
  "approval_reason": "why"
}}

Construct real tool_input values using the risk event data. Use actual shipment_id, container_id, etc."""

    try:
        response = llm.invoke([
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        parsed = _extract_json(response.content)

        if not parsed or "steps" not in parsed:
            logger.warning("AGENT_PLAN: unparseable LLM response, falling back")
            from orchestrator.nodes import plan as det_plan
            return det_plan(state)

        draft: List[PlanStep] = []
        seen_tools: set = set()
        for s in parsed["steps"]:
            tool_name = s.get("tool", "")
            if tool_name not in TOOL_MAP:
                logger.warning("AGENT_PLAN: unknown tool '%s', skipping", tool_name)
                continue
            if tool_name in seen_tools:
                logger.debug("AGENT_PLAN: skipping duplicate %s", tool_name)
                continue
            seen_tools.add(tool_name)

            llm_input = s.get("tool_input", {})
            if not isinstance(llm_input, dict) or not llm_input:
                from orchestrator.nodes import _build_tool_input
                llm_input = _build_tool_input(tool_name, ri, state)
                logger.debug("AGENT_PLAN: empty tool_input for %s, used fallback builder", tool_name)

            draft.append(PlanStep(
                step=len(draft) + 1,
                action=s.get("action", f"Execute {tool_name}"),
                tool=tool_name,
                tool_input=llm_input,
                reason=s.get("reason", ""),
            ))

        if not draft and ri.get("risk_tier") not in ("LOW", None):
            logger.warning("AGENT_PLAN: LLM returned 0 valid steps for %s tier, falling back",
                           ri.get("risk_tier"))
            from orchestrator.nodes import plan as det_plan
            return det_plan(state)

        reasoning = parsed.get("reasoning", "")
        requires_approval = parsed.get("requires_approval",
                                        ri.get("risk_tier") in ("CRITICAL", "HIGH"))

        logger.info("AGENT_PLAN: %d steps, reasoning=%s", len(draft), reasoning[:80])
        return {
            "draft_plan": draft,
            "plan_revised": False,
            "requires_approval": requires_approval,
            "approval_reason": parsed.get("approval_reason", state.get("primary_issue", "")),
            "llm_reasoning": reasoning,
        }

    except Exception as exc:
        logger.error("AGENT_PLAN failed (%s), falling back to deterministic", exc)
        from orchestrator.nodes import plan as det_plan
        return det_plan(state)


# ── Agentic Reflect (POST-EXECUTION: analyzes real results) ──────────

REFLECT_SYSTEM = """You are a GDP/FDA compliance auditor for pharmaceutical cold-chain logistics.
You have received the EXECUTION RESULTS of an automated response to a risk event.
Your job: analyze what the tools actually did, check result quality, and identify genuine gaps.

You evaluate TWO things:
1. MANDATORY TOOL PRESENCE: Were the required tools executed and did they succeed?
2. RESULT QUALITY & CONTEXT: Are the results adequate? Does the situation require additional tools?

QUALITY CHECKS (these can trigger corrections even if mandatory tools passed):
- compliance_agent returned "violation" + "quarantine" but cold_storage_agent was not called → cold storage transfer needed
- cold_storage_agent returned suitability_score < 50 or suitability_tier="marginal"/"poor" → facility inadequate, retry
- spoilage_probability > 0.5 and CRITICAL tier but route_agent not called → rerouting may reduce transit time
- transit_phase is "air_handoff"/"customs_clearance" and route_agent was not called → rerouting evaluation needed
- delay_class is "critical" or "developing" and scheduling_agent was not called → downstream scheduling needed
- spoilage_probability > 0.6 and HIGH/CRITICAL tier but insurance_agent not called → financial protection needed
- notification_agent has agentic_workflow=false for HIGH/CRITICAL → stakeholder delivery incomplete
- compliance mandates "quarantine"/"destroy" but scheduling didn't reschedule any deliveries → gap

PREFIX RULES:
- "GAP [tool_name]:" for mandatory tools that are MISSING or FAILED
- "QUALITY [tool_name]:" for context/quality issues that need a NEW or RETRY tool
- "OK:" for checks that passed

If ALL mandatory tools succeeded AND no quality issues found, set has_gaps=false.
Return ONLY valid JSON."""


def reflect_llm(state: OrchestratorState) -> dict:
    """Post-execution reflection: LLM analyzes REAL tool outputs and identifies gaps.

    notification_agent is always deferred to post-approval so it is excluded
    from gap analysis here.  needs_revision is always True because the deferred
    notification must be proposed in the revise step.
    """
    ri = state["risk_input"]
    tier = ri.get("risk_tier", "LOW")

    if tier == "LOW":
        return {"reflection_notes": ["LOW risk: monitoring only."], "needs_revision": False}

    tool_results = state.get("tool_results", [])
    deferred = set(state.get("deferred_tools", []))

    if not tool_results:
        notes = [f"GAP [execution]: No tools were executed for {tier} risk event."]
        if deferred:
            notes.append(f"DEFERRED: {', '.join(deferred)} held for post-approval")
        return {"reflection_notes": notes, "needs_revision": True}

    llm = get_llm()
    if llm is None:
        from orchestrator.nodes import reflect as det_reflect
        return det_reflect(state)

    executed_tools = [r["tool"] for r in tool_results]
    succeeded = [r["tool"] for r in tool_results if r.get("success")]
    failed = [r["tool"] for r in tool_results if not r.get("success")]

    results_text = ""
    for r in tool_results:
        status = "SUCCESS" if r.get("success") else "FAILED"
        result_data = r.get("result", {})
        summary_parts = []
        if isinstance(result_data, dict):
            for k, v in list(result_data.items())[:6]:
                summary_parts.append(f"{k}={repr(v)[:80]}")
        results_text += f"\n  [{status}] {r['tool']}: {', '.join(summary_parts)}"

    required_for_tier = {
        "CRITICAL": ["compliance_agent", "cold_storage_agent", "insurance_agent"],
        "HIGH": ["compliance_agent"],
        "MEDIUM": ["compliance_agent"],
    }
    required = required_for_tier.get(tier, [])
    missing = [t for t in required if t not in executed_tools and t not in deferred]

    transit_phase = ri.get("transit_phase", "")
    delay_class = ri.get("delay_class", "")
    spoilage = ri.get("ml_spoilage_probability", 0)

    user_msg = f"""Analyze these EXECUTION RESULTS for a {tier} risk event.

NOTE: notification_agent is DEFERRED to post-approval — do NOT flag it as missing.

SHIPMENT CONTEXT:
  shipment_id: {ri.get('shipment_id')}
  risk_tier: {tier}
  product: {ri.get('product_type')}
  transit_phase: {transit_phase}
  delay_class: {delay_class}
  spoilage_probability: {spoilage}
  hours_to_breach: {ri.get('hours_to_breach', 'N/A')}
  primary_issue: {state.get('primary_issue', '')}
  fused_risk_score: {ri.get('fused_risk_score', 0)}

MANDATORY TOOLS FOR {tier} (excluding deferred): {required}
  Flag as "GAP [tool]:" if missing or failed.

CONTEXT-DEPENDENT TOOLS (flag as QUALITY if situation warrants):
  - cold_storage_agent: needed if compliance found "violation"/"quarantine" and tier >= HIGH
  - route_agent: needed if transit_phase is "air_handoff"/"customs_clearance", OR CRITICAL with spoilage > 0.5
  - scheduling_agent: needed if delay_class is "critical" or "developing"
  - insurance_agent: needed if spoilage_probability > 0.6 and tier >= HIGH

TOOLS EXECUTED: {executed_tools}
SUCCEEDED: {succeeded}
FAILED: {failed}
MISSING FROM MANDATORY: {missing}
DEFERRED TO POST-APPROVAL: {list(deferred)}

EXECUTION RESULTS:{results_text}

Evaluate:
1. Are any MANDATORY tools missing or failed? → "GAP [tool_name]:"
2. Do the results QUALITY warrant additional tools? → "QUALITY [tool_name]:"
   - compliance_status = "violation"/"quarantine" but cold_storage not called → QUALITY
   - cold_storage suitability_score < 50 → QUALITY (retry)
   - CRITICAL with spoilage > 0.5 but no route_agent → QUALITY
3. If everything is adequate, note "OK: all checks passed"

Respond with ONLY this JSON:
{{
  "notes": ["GAP/QUALITY/OK [context]: description"],
  "has_gaps": true/false,
  "overall_assessment": "adequate or inadequate"
}}"""

    try:
        response = llm.invoke([
            {"role": "system", "content": REFLECT_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        parsed = _extract_json(response.content)

        if not parsed or "notes" not in parsed:
            from orchestrator.nodes import reflect as det_reflect
            return det_reflect(state)

        notes = parsed.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)]

        strip_tools = {"triage_agent"}
        medium_optional = {"route_agent", "scheduling_agent"}
        cleaned_notes = []
        for n in notes:
            n_str = str(n)
            n_upper = n_str.upper()
            if "NOTIFICATION" in n_upper and ("GAP" in n_upper or "MISSING" in n_upper):
                logger.debug("AGENT_REFLECT: stripping notification GAP (deferred by design)")
                continue
            if "TRIAGE" in n_upper and "GAP" in n_upper:
                continue
            if "GAP" in n_upper and tier == "MEDIUM":
                gap_tool = None
                for ot in medium_optional:
                    if ot in n_str.lower():
                        gap_tool = ot
                        break
                if gap_tool and gap_tool not in set(failed):
                    continue
            cleaned_notes.append(n)

        has_quality_issues = any(
            "GAP" in str(n).upper() or "QUALITY" in str(n).upper()
            for n in cleaned_notes
        )

        if deferred:
            cleaned_notes.append(f"DEFERRED: {', '.join(deferred)} held for post-approval execution")

        if not cleaned_notes:
            cleaned_notes.append(
                f"All mandatory tools for {tier} executed successfully. Response adequate."
            )

        logger.info("AGENT_REFLECT: %d notes (cleaned from %d), quality_issues=%s, deferred=%s",
                     len(cleaned_notes), len(notes), has_quality_issues, list(deferred))
        return {
            "reflection_notes": cleaned_notes,
            "needs_revision": True,
        }

    except Exception as exc:
        logger.error("AGENT_REFLECT failed (%s), falling back", exc)
        from orchestrator.nodes import reflect as det_reflect
        return det_reflect(state)


# ── Agentic Revise (proposes CORRECTIVE actions based on real results) ─

REVISE_SYSTEM = """You are a pharmaceutical cold-chain corrective action planner.
You receive EXECUTION RESULTS and REFLECTION NOTES that identify gaps and quality issues.
Your job: propose corrective steps to fix GAP and QUALITY issues.

RULES:
- For "GAP [tool]:" notes → propose that tool (it was missing or failed).
- For "QUALITY [tool]:" notes → propose that tool (it was not called but the situation needs it).
- Do NOT re-run tools that already SUCCEEDED unless reflection explicitly flags a quality problem with their output.
- Do NOT propose triage_agent (it's a ranking tool, not corrective).
- Each tool appears AT MOST ONCE.
- Construct real tool_input using the shipment data.
- Return ONLY valid JSON."""


def revise_llm(state: OrchestratorState) -> dict:
    """Generate corrective plan: GAP/QUALITY tools + always-deferred notification."""
    llm = get_llm()
    if llm is None:
        from orchestrator.nodes import revise as det_revise
        return det_revise(state)

    ri = state["risk_input"]
    tool_results = state.get("tool_results", [])
    notes = state.get("reflection_notes", [])
    deferred = set(state.get("deferred_tools", []))

    succeeded = [r["tool"] for r in tool_results if r.get("success")]
    failed = [r["tool"] for r in tool_results if not r.get("success")]

    results_text = ""
    for r in tool_results:
        status = "SUCCESS" if r.get("success") else "FAILED"
        results_text += f"\n  [{status}] {r['tool']}"

    notes_text = "\n".join(f"  - {n}" for n in notes)

    tier = ri.get("risk_tier", "LOW")
    required_for_tier = {
        "CRITICAL": ["compliance_agent", "cold_storage_agent", "insurance_agent"],
        "HIGH": ["compliance_agent"],
        "MEDIUM": ["compliance_agent"],
    }
    mandatory = required_for_tier.get(tier, [])

    user_msg = f"""Generate CORRECTIVE steps to fix gaps and quality issues.
Do NOT include notification_agent — it is handled separately.

SHIPMENT CONTEXT:
  shipment_id: {ri.get('shipment_id')}
  container_id: {ri.get('container_id')}
  window_id: {ri.get('window_id')}
  risk_tier: {tier}
  product_type: {ri.get('product_type')}
  transit_phase: {ri.get('transit_phase')}
  delay_class: {ri.get('delay_class', '')}
  ml_spoilage_probability: {ri.get('ml_spoilage_probability')}

FIRST EXECUTION RESULTS:{results_text}

ALREADY SUCCEEDED (do NOT re-run unless quality flagged): {succeeded}
FAILED (retry): {failed}

REFLECTION NOTES:
{notes_text}

RULES:
- For each "GAP [tool]:" → propose that missing/failed tool
- For each "QUALITY [tool]:" → propose that tool (it's needed by context)
- Do NOT propose triage_agent or notification_agent
- Do NOT re-run already-succeeded tools unless reflection calls out quality issue
- If no GAP or QUALITY issues found, return empty steps

Return ONLY corrective steps as JSON:
{{
  "corrective_reasoning": "1-2 sentences on what needs fixing",
  "steps": [
    {{"step": 1, "action": "...", "tool": "tool_name", "tool_input": {{...}}, "reason": "..."}}
  ]
}}"""

    try:
        response = llm.invoke([
            {"role": "system", "content": REVISE_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        parsed = _extract_json(response.content)

        if not parsed or "steps" not in parsed:
            logger.warning("AGENT_REVISE: unparseable, falling back to deterministic")
            from orchestrator.nodes import revise as det_revise
            return det_revise(state)

        notes_blob = " ".join(state.get("reflection_notes", [])).upper()
        quality_tools = set()
        for tool_key in TOOL_MAP:
            if f"QUALITY [{tool_key.upper()}]" in notes_blob or f"QUALITY [{tool_key}]" in notes_blob:
                quality_tools.add(tool_key)

        revised: List[PlanStep] = []
        seen_tools: set = set()
        succeeded_set = set(succeeded)
        mandatory_set = set(mandatory)
        allowed_set = mandatory_set | quality_tools | set(failed)

        for s in parsed["steps"]:
            tool_name = s.get("tool", "")
            if tool_name not in TOOL_MAP:
                continue
            if tool_name in seen_tools:
                continue
            if tool_name in ("triage_agent", "notification_agent"):
                continue
            if tool_name in succeeded_set and tool_name not in quality_tools:
                logger.debug("AGENT_REVISE: skipping already-succeeded %s", tool_name)
                continue
            if tool_name not in allowed_set:
                logger.debug("AGENT_REVISE: skipping %s (not in allowed set)", tool_name)
                continue
            seen_tools.add(tool_name)
            llm_input = s.get("tool_input", {})
            if not isinstance(llm_input, dict) or not llm_input:
                from orchestrator.nodes import _build_tool_input
                llm_input = _build_tool_input(tool_name, ri, state)
            revised.append(PlanStep(
                step=len(revised) + 1,
                action=s.get("action", f"Execute {tool_name}"),
                tool=tool_name,
                tool_input=llm_input,
                reason=s.get("reason", ""),
            ))

        if "notification_agent" in deferred:
            from orchestrator.nodes import _build_tool_input
            revised.append(PlanStep(
                step=len(revised) + 1,
                action="Send stakeholder notification (deferred to post-approval)",
                tool="notification_agent",
                tool_input=_build_tool_input("notification_agent", ri, state),
                reason="Notification deferred: stakeholders must not be alerted before human validates the response",
            ))

        corrective_reasoning = parsed.get("corrective_reasoning", "")
        existing_reasoning = state.get("llm_reasoning", "")
        combined_reasoning = f"{existing_reasoning} | Correction: {corrective_reasoning}" if corrective_reasoning else existing_reasoning

        logger.info("AGENT_REVISE: %d steps (%d corrective + deferred)", len(revised), len(revised))
        return {
            "revised_plan": revised,
            "plan_revised": True,
            "active_plan": revised,
            "llm_reasoning": combined_reasoning,
        }

    except Exception as exc:
        logger.error("AGENT_REVISE failed (%s), falling back", exc)
        from orchestrator.nodes import revise as det_revise
        return det_revise(state)


# ── Agentic Observe (post-execution reflection) ──────────────────────

OBSERVE_SYSTEM = """You are a pharmaceutical cold-chain operations supervisor.
You review tool execution results and decide if the response was adequate.

If a critical tool failed or returned inadequate results, recommend specific
corrective actions. If all tools succeeded, confirm the response is adequate.
Return ONLY valid JSON."""


def observe_llm(state: OrchestratorState) -> dict:
    """LLM reviews execution results and decides if re-planning is needed."""
    ri = state["risk_input"]
    tier = ri.get("risk_tier", "LOW")

    if tier in ("LOW", "MEDIUM"):
        return {"observation": "adequate", "needs_replan": False}

    tool_results = state.get("tool_results", [])
    errors = state.get("execution_errors", [])

    if not tool_results:
        return {"observation": "no tools executed", "needs_replan": tier in ("CRITICAL", "HIGH")}

    llm = get_llm()
    if llm is None:
        failed = [r["tool"] for r in tool_results if not r.get("success")]
        return {
            "observation": f"deterministic check: {len(failed)} failures",
            "needs_replan": len(failed) > 0 and tier == "CRITICAL",
            "failed_tools": failed,
        }

    results_text = ""
    for r in tool_results:
        status = "SUCCESS" if r.get("success") else "FAILED"
        result_data = r.get("result", {})
        result_summary = ""
        if isinstance(result_data, dict):
            result_summary = ", ".join(
                f"{k}={repr(v)[:60]}" for k, v in list(result_data.items())[:5]
            )
        results_text += f"\n  [{status}] {r['tool']}: {result_summary}"

    if errors:
        results_text += "\n  ERRORS: " + "; ".join(errors)

    user_msg = f"""Review these execution results for a {tier} risk event.

CONTEXT:
  shipment_id: {ri.get('shipment_id')}
  risk_tier: {tier}
  product: {ri.get('product_type')}
  spoilage_probability: {ri.get('ml_spoilage_probability')}

EXECUTION RESULTS:{results_text}

Questions to answer:
1. Did cold_storage_agent find a viable facility? (check status != "no_facility_found")
2. Did compliance_agent detect violations that need escalation?
3. Were any critical tools missing from execution?
4. Is the overall response adequate for a {tier} event?

Return ONLY this JSON:
{{
  "observation": "brief assessment of execution quality",
  "adequate": true/false,
  "issues": ["list of specific issues found, empty if adequate"],
  "recommended_actions": ["additional tools to run or actions needed, empty if adequate"]
}}"""

    try:
        response = llm.invoke([
            {"role": "system", "content": OBSERVE_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        parsed = _extract_json(response.content)

        if not parsed:
            return {"observation": "unparseable", "needs_replan": False}

        adequate = parsed.get("adequate", True)
        issues = parsed.get("issues", [])
        recommended = parsed.get("recommended_actions", [])

        logger.info("AGENT_OBSERVE: adequate=%s, issues=%d, recommended=%d",
                     adequate, len(issues), len(recommended))
        return {
            "observation": parsed.get("observation", ""),
            "needs_replan": not adequate and tier == "CRITICAL",
            "observation_issues": issues,
            "observation_actions": recommended,
        }

    except Exception as exc:
        logger.error("AGENT_OBSERVE failed (%s)", exc)
        return {"observation": f"error: {exc}", "needs_replan": False}
