"""
Orchestrator state schema for the act-first, reflect-on-results loop.

New pipeline: Plan → Execute → Observe → Reflect → Revise → [Approval] → Re-Execute
This TypedDict flows through every node in the LangGraph StateGraph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class PlanStep(TypedDict):
    step: int
    action: str
    tool: str
    tool_input: Dict[str, Any]
    reason: str


class ToolResult(TypedDict):
    tool: str
    input: Dict[str, Any]
    result: Dict[str, Any]
    success: bool


class OrchestratorState(TypedDict, total=False):
    # ── Input from risk engine ──
    risk_input: Dict[str, Any]

    # ── Interpretation ──
    severity: str
    primary_issue: str
    urgency: str

    # ── Planning ──
    draft_plan: List[PlanStep]
    llm_reasoning: str

    # ── First Execution (act-first) ──
    tool_results: List[ToolResult]
    execution_errors: List[str]
    cascade_context: Dict[str, Any]
    deferred_tools: List[str]  # tools skipped in first pass (e.g. notification_agent)

    # ── Post-Execution Reflection ──
    observation: str
    reflection_notes: List[str]
    needs_revision: bool
    observation_issues: List[str]
    observation_actions: List[str]

    # ── Revision (corrective plan based on real results) ──
    revised_plan: List[PlanStep]
    plan_revised: bool
    active_plan: List[PlanStep]

    # ── Re-Execution ──
    revised_tool_results: List[ToolResult]
    revised_execution_errors: List[str]

    # ── Human Review ──
    requires_approval: bool
    approval_reason: str
    approval_id: Optional[str]
    awaiting_approval: bool
    review_status: str  # "corrections_proposed" | "adequate_pending_confirmation"

    # ── Fallback ──
    fallback_plan: List[PlanStep]

    # ── Loop control ──
    replan_count: int

    # ── Output ──
    decision_summary: str
    audit_log_summary: str
    confidence: float
    final_output: Dict[str, Any]
