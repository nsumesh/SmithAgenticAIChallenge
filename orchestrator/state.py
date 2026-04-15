"""
Orchestrator state schema for the plan-reflect-execute loop.
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
    reflection_notes: List[str]
    plan_revised: bool
    revised_plan: List[PlanStep]
    active_plan: List[PlanStep]
    llm_reasoning: str

    # ── Execution ──
    tool_results: List[ToolResult]
    execution_errors: List[str]

    # ── Fallback ──
    fallback_plan: List[PlanStep]

    # ── Approval ──
    requires_approval: bool
    approval_reason: str
    approval_id: Optional[str]
    awaiting_approval: bool        # True when plan is ready but execution is paused

    # ── Cascade ──
    cascade_context: Dict[str, Any]   # keyed by tool_name; accumulates results during execute

    # ── Observation (post-execution) ──
    observation: str
    needs_replan: bool
    observation_issues: List[str]
    observation_actions: List[str]
    replan_count: int              # tracks iterations to prevent infinite loops

    # ── Output ──
    decision_summary: str
    audit_log_summary: str
    confidence: float
    final_output: Dict[str, Any]
