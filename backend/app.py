"""
FastAPI backend for AI Cargo Monitoring.

Serves the risk-scored data to the React dashboard and provides
tool-execution endpoints that the orchestrator will call.

Run:  uvicorn backend.app:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditRecord,
    RiskOverview,
    ShipmentSummary,
    WindowRisk,
)
from tools.approval_workflow import _PENDING_APPROVALS, decide as approve_decide, get_pending
from tools import TOOL_MAP
from orchestrator.graph import run_orchestrator, get_graph_mermaid
from src.context_assembler import build_window_context
from src.data_loader import load_product_profiles

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent
SCORED_CSV = BASE / "artifacts" / "scored_windows.csv"
AUDIT_DIR = BASE / "audit_logs"

app = FastAPI(title="AI Cargo Monitor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory caches ─────────────────────────────────────────────────

_df: Optional[pd.DataFrame] = None
_profiles: Optional[dict] = None


def _get_df() -> pd.DataFrame:
    global _df
    if _df is None:
        if not SCORED_CSV.exists():
            raise HTTPException(503, "Run `python pipeline.py train` first")
        _df = pd.read_csv(SCORED_CSV)
    return _df


def _get_profiles() -> dict:
    global _profiles
    if _profiles is None:
        _profiles = load_product_profiles()
    return _profiles


# ── WebSocket connections ────────────────────────────────────────────

_ws_clients: List[WebSocket] = []


async def _broadcast(event: dict):
    for ws in list(_ws_clients):
        try:
            await ws.send_json(event)
        except Exception:
            _ws_clients.remove(ws)


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)


# ── Risk overview ────────────────────────────────────────────────────

@app.get("/api/risk/overview", response_model=RiskOverview)
def risk_overview():
    df = _get_df()
    tier_counts = df["risk_tier"].value_counts().to_dict()
    total = len(df)
    tier_pcts = {k: round(v / total * 100, 1) for k, v in tier_counts.items()}

    top = _build_shipment_summaries(df, top_n=10)
    return RiskOverview(
        total_windows=total,
        total_shipments=df["shipment_id"].nunique(),
        tier_counts=tier_counts,
        tier_pcts=tier_pcts,
        top_risky_shipments=top,
    )


# ── Shipments ────────────────────────────────────────────────────────

@app.get("/api/shipments", response_model=List[ShipmentSummary])
def list_shipments(risk_tier: Optional[str] = Query(None)):
    df = _get_df()
    summaries = _build_shipment_summaries(df, top_n=None)
    if risk_tier:
        summaries = [s for s in summaries if s.latest_risk_tier == risk_tier]
    return summaries


@app.get("/api/shipments/{shipment_id}/windows", response_model=List[WindowRisk])
def shipment_windows(shipment_id: str):
    df = _get_df()
    sub = df[df["shipment_id"] == shipment_id]
    if sub.empty:
        raise HTTPException(404, f"Shipment {shipment_id} not found")
    return [_row_to_window(row) for _, row in sub.iterrows()]


# ── Windows ──────────────────────────────────────────────────────────

@app.get("/api/windows", response_model=List[WindowRisk])
def list_windows(
    risk_tier: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    limit: int = Query(200, le=2000),
    offset: int = Query(0),
):
    df = _get_df()
    if risk_tier:
        df = df[df["risk_tier"] == risk_tier]
    if product_id:
        df = df[df["product_id"] == product_id]
    df = df.sort_values("final_score", ascending=False)
    page = df.iloc[offset : offset + limit]
    return [_row_to_window(row) for _, row in page.iterrows()]


@app.get("/api/windows/{window_id}", response_model=WindowRisk)
def get_window(window_id: str):
    df = _get_df()
    row = df[df["window_id"] == window_id]
    if row.empty:
        raise HTTPException(404, f"Window {window_id} not found")
    return _row_to_window(row.iloc[0])


# ── Risk engine output (for orchestrator) ────────────────────────────

@app.get("/api/risk/score-window/{window_id}")
def score_window(window_id: str):
    """
    Return the enriched risk engine output for a single window in the format
    expected by the orchestrator (system_prompt.md input contract).

    Extends the base risk fields with cascade context:
      delay_ratio, delay_class, hours_to_breach, facility, product_cost,
      window_end (for ETA computation in the cascade).
    """
    df = _get_df()
    profiles = _get_profiles()

    try:
        ctx = build_window_context(window_id, df, profiles)
    except KeyError:
        raise HTTPException(404, f"Window {window_id} not found")

    return {
        # Core identity
        "shipment_id": ctx["shipment_id"],
        "container_id": ctx["container_id"],
        "window_id": ctx["window_id"],
        "leg_id": ctx["leg_id"],
        "product_type": ctx["product_id"],
        "transit_phase": ctx["transit_phase"],
        "window_end": ctx["window_end"],

        # Risk scores
        "risk_tier": ctx["risk_tier"],
        "fused_risk_score": ctx["final_score"],
        "ml_spoilage_probability": ctx["ml_score"],
        "deterministic_rule_flags": ctx["det_rules_fired"],
        "key_drivers": [],
        "recommended_actions_from_risk_engine": ctx["recommended_actions"],
        "confidence_score": round(1.0 - abs(ctx["det_score"] - ctx["ml_score"]), 4),

        # Cascade context fields
        "delay_ratio": ctx["delay_ratio"],
        "delay_class": ctx["delay_class"],
        "hours_to_breach": ctx["hours_to_breach"],
        "current_delay_min": ctx["current_delay_min"],
        "facility": ctx["facility"],
        "product_cost": ctx["product_cost"],

        "operational_constraints": [],
        "available_tools": list(TOOL_MAP.keys()),
    }


# ── Audit logs ───────────────────────────────────────────────────────

@app.get("/api/audit-logs", response_model=List[AuditRecord])
def list_audit_logs(
    shipment_id: Optional[str] = Query(None),
    risk_tier: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    records = _load_audit_records()
    if shipment_id:
        records = [r for r in records if r.get("shipment_id") == shipment_id]
    if risk_tier:
        records = [r for r in records if r.get("risk_tier") == risk_tier]
    return records[:limit]


# ── Tool execution ───────────────────────────────────────────────────

@app.post("/api/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, payload: Dict[str, Any]):
    if tool_name not in TOOL_MAP:
        raise HTTPException(404, f"Tool '{tool_name}' not found. Available: {list(TOOL_MAP.keys())}")
    tool = TOOL_MAP[tool_name]
    result = tool.invoke(payload)
    await _broadcast({"type": "tool_executed", "tool": tool_name, "result": result})
    return result


# ── Approval workflow ────────────────────────────────────────────────

@app.get("/api/approvals/pending", response_model=List[ApprovalRequest])
def pending_approvals():
    return get_pending()


@app.post("/api/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, body: ApprovalDecision):
    result = approve_decide(approval_id, body.decision, body.decided_by)
    if "error" in result:
        raise HTTPException(404, result["error"])
    await _broadcast({"type": "approval_decided", "result": result})
    return result


# ── Orchestrator ─────────────────────────────────────────────────────

_orchestrator_history: List[Dict[str, Any]] = []


# ── Triage ───────────────────────────────────────────────────────────────

@app.get("/api/triage/critical-shipments")
def triage_critical_shipments(limit: int = Query(20, le=100)):
    """
    Pull all CRITICAL and HIGH shipments from scored data, run triage ranking,
    and return priority-ordered list with real excursion context.

    This is the pre-orchestration step — use recommended_orchestration_order
    to decide which window IDs to pass to /api/orchestrator/run-batch.
    """
    df = _get_df()

    # Get the worst window per shipment for CRITICAL and HIGH tiers
    at_risk = df[df["risk_tier"].isin(["CRITICAL", "HIGH"])]
    if at_risk.empty:
        return {"tool": "triage_agent", "status": "no_action_needed", "total_shipments": 0, "priority_list": []}

    # One row per shipment — the highest-scoring window
    worst_per_shipment = (
        at_risk.sort_values("final_score", ascending=False)
        .drop_duplicates(subset=["shipment_id"])
        .head(limit)
    )

    shipments_input = [
        {
            "shipment_id": str(row["shipment_id"]),
            "risk_tier": str(row["risk_tier"]),
            "fused_risk_score": float(row["final_score"]),
            "product_id": str(row["product_id"]),
            "container_id": str(row.get("container_id", "")),
            "transit_phase": str(row.get("transit_phase", "")),
        }
        for _, row in worst_per_shipment.iterrows()
    ]

    from tools.triage_agent import _execute as triage_execute
    result = triage_execute(shipments=shipments_input, enrich=True)
    return result


@app.post("/api/triage/rank")
async def triage_rank(shipments: List[Dict[str, Any]]):
    """
    Rank a caller-supplied list of shipment dicts by urgency.
    Each dict must have: shipment_id, risk_tier, fused_risk_score, product_id.
    container_id and transit_phase are optional.
    """
    from tools.triage_agent import _execute as triage_execute
    result = triage_execute(shipments=shipments, enrich=True)
    await _broadcast({"type": "triage_completed", "result": result})
    return result


@app.post("/api/orchestrator/run/{window_id}")
async def orchestrate_window(window_id: str):
    """Feed a window's risk output through the full orchestration agent."""
    risk_data = score_window(window_id)
    decision = run_orchestrator(risk_data)
    decision["_window_id"] = window_id
    _orchestrator_history.append(decision)
    await _broadcast({"type": "orchestrator_decision", "decision": decision})
    return decision


@app.post("/api/orchestrator/run-batch")
async def orchestrate_batch(window_ids: List[str]):
    """Orchestrate multiple windows (e.g. all CRITICAL windows)."""
    results = []
    for wid in window_ids[:20]:
        try:
            risk_data = score_window(wid)
            decision = run_orchestrator(risk_data)
            decision["_window_id"] = wid
            _orchestrator_history.append(decision)
            results.append(decision)
        except HTTPException:
            results.append({"_window_id": wid, "error": "window not found"})
    await _broadcast({"type": "orchestrator_batch", "count": len(results)})
    return results


@app.get("/api/orchestrator/history")
def orchestrator_history(limit: int = Query(50, le=200)):
    return list(reversed(_orchestrator_history[-limit:]))


@app.get("/api/graph/mermaid")
def graph_mermaid():
    """Return the Mermaid diagram of the orchestration graph."""
    return {"mermaid": get_graph_mermaid()}


@app.get("/api/graph/topology")
def graph_topology():
    """Return a JSON description of the full system graph topology."""
    return {
        "layers": [
            {
                "id": "L1", "name": "Data & Ingestion",
                "nodes": [
                    {"id": "sensors", "label": "Smart Containers"},
                    {"id": "ingest", "label": "Window Aggregation"},
                ],
                "edges": [{"from": "sensors", "to": "ingest"}],
            },
            {
                "id": "L2", "name": "Risk Scoring Engine",
                "nodes": [
                    {"id": "features", "label": "Feature Engineering"},
                    {"id": "det", "label": "Deterministic Rules"},
                    {"id": "ml", "label": "XGBoost Predictor"},
                    {"id": "fusion", "label": "Risk Fusion"},
                ],
                "edges": [
                    {"from": "features", "to": "det"},
                    {"from": "features", "to": "ml"},
                    {"from": "det", "to": "fusion"},
                    {"from": "ml", "to": "fusion"},
                ],
            },
            {
                "id": "L3", "name": "Orchestration Agent",
                "nodes": [
                    {"id": "interpret", "label": "Interpret Risk"},
                    {"id": "plan", "label": "Generate Plan"},
                    {"id": "reflect", "label": "Self-Critique"},
                    {"id": "revise", "label": "Revise Plan"},
                    {"id": "execute", "label": "Execute Tools"},
                    {"id": "output", "label": "Compile Decision"},
                ],
                "edges": [
                    {"from": "interpret", "to": "plan"},
                    {"from": "plan", "to": "reflect"},
                    {"from": "reflect", "to": "revise", "label": "has gaps"},
                    {"from": "reflect", "to": "execute", "label": "plan OK"},
                    {"from": "revise", "to": "execute"},
                    {"from": "execute", "to": "output"},
                ],
            },
            {
                "id": "L4", "name": "Agent Tools",
                "nodes": [
                    {"id": "t_route", "label": "Route Agent"},
                    {"id": "t_cold", "label": "Cold Storage"},
                    {"id": "t_notify", "label": "Notification"},
                    {"id": "t_compliance", "label": "Compliance"},
                    {"id": "t_schedule", "label": "Scheduling"},
                    {"id": "t_insurance", "label": "Insurance"},
                    {"id": "t_triage", "label": "Triage"},
                    {"id": "t_approval", "label": "Approval"},
                ],
                "edges": [],
            },
            {
                "id": "L5", "name": "Human-in-the-Loop",
                "nodes": [
                    {"id": "dashboard", "label": "Ops Dashboard"},
                    {"id": "approve", "label": "Approval Queue"},
                ],
                "edges": [{"from": "approve", "to": "dashboard"}],
            },
        ],
        "cross_layer_edges": [
            {"from": "ingest", "to": "features"},
            {"from": "fusion", "to": "interpret"},
            {"from": "execute", "to": "t_route"},
            {"from": "execute", "to": "t_cold"},
            {"from": "execute", "to": "t_notify"},
            {"from": "execute", "to": "t_compliance"},
            {"from": "execute", "to": "t_insurance"},
            {"from": "execute", "to": "t_approval"},
            {"from": "t_approval", "to": "approve"},
            {"from": "output", "to": "dashboard"},
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _build_shipment_summaries(
    df: pd.DataFrame, top_n: Optional[int] = 10,
) -> List[ShipmentSummary]:
    groups = df.groupby("shipment_id")
    summaries = []
    for sid, grp in groups:
        tier_vc = grp["risk_tier"].value_counts()
        total = len(grp)
        summaries.append(ShipmentSummary(
            shipment_id=sid,
            containers=grp["container_id"].unique().tolist(),
            products=grp["product_id"].unique().tolist(),
            total_windows=total,
            latest_risk_tier=grp.sort_values("window_start" if "window_start" in grp.columns else "window_id").iloc[-1]["risk_tier"],
            max_fused_score=round(float(grp["final_score"].max()), 4),
            pct_critical=round(tier_vc.get("CRITICAL", 0) / total * 100, 1),
            pct_high=round(tier_vc.get("HIGH", 0) / total * 100, 1),
        ))
    summaries.sort(key=lambda s: s.max_fused_score, reverse=True)
    if top_n:
        return summaries[:top_n]
    return summaries


def _row_to_window(row) -> WindowRisk:
    return WindowRisk(
        window_id=row["window_id"],
        shipment_id=row["shipment_id"],
        container_id=row["container_id"],
        product_id=row["product_id"],
        leg_id=row["leg_id"],
        window_start=str(row.get("window_start", "")),
        window_end=str(row.get("window_end", "")),
        transit_phase=str(row.get("transit_phase", "")),
        avg_temp_c=round(float(row.get("avg_temp_c", 0)), 2),
        det_score=round(float(row.get("det_score", 0)), 4),
        ml_score=round(float(row.get("ml_score", 0)), 4),
        final_score=round(float(row.get("final_score", 0)), 4),
        risk_tier=row.get("risk_tier", "LOW"),
        det_rules_fired=str(row.get("det_rules_fired", "")),
        recommended_actions=str(row.get("recommended_actions", "")),
        requires_human_approval=bool(row.get("requires_human_approval", False)),
    )


def _load_audit_records() -> List[dict]:
    records = []
    all_paths = sorted(AUDIT_DIR.glob("audit_*.jsonl")) + sorted(AUDIT_DIR.glob("compliance_events.jsonl"))
    for path in all_paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records
