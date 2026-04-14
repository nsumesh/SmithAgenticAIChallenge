from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class ShipmentRiskSummary(BaseModel):
    shipment_id: str
    container_id: str
    risk_tier: str
    fused_risk_score: float
    product_id: str
    transit_phase: str


class TriageInput(BaseModel):
    shipments: List[ShipmentRiskSummary] = Field(
        description="List of shipments with their current risk data"
    )


def _execute(shipments: List[ShipmentRiskSummary]) -> dict:
    tier_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    items = [s.model_dump() if hasattr(s, "model_dump") else s for s in shipments]
    ranked = sorted(
        items,
        key=lambda s: (
            tier_order.get(s.get("risk_tier", "LOW"), 3),
            -s.get("fused_risk_score", 0),
        ),
    )
    priority_list = []
    for rank, s in enumerate(ranked, 1):
        priority_list.append({
            "priority_rank": rank,
            "shipment_id": s.get("shipment_id", ""),
            "container_id": s.get("container_id", ""),
            "risk_tier": s.get("risk_tier", ""),
            "fused_risk_score": s.get("fused_risk_score", 0.0),
            "product_id": s.get("product_id", ""),
            "needs_immediate_attention": s.get("risk_tier", "") in ("CRITICAL", "HIGH"),
        })
    return {
        "tool": "triage_agent",
        "status": "ranked",
        "total_shipments": len(ranked),
        "critical_count": sum(1 for s in ranked if s.get("risk_tier") == "CRITICAL"),
        "high_count": sum(1 for s in ranked if s.get("risk_tier") == "HIGH"),
        "priority_list": priority_list,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


triage_tool = StructuredTool.from_function(
    func=_execute,
    name="triage_agent",
    description=(
        "Rank multiple shipments by urgency.  Takes a list of shipment "
        "risk summaries and returns a priority-ordered list.  CRITICAL "
        "and HIGH tiers are flagged for immediate attention."
    ),
    args_schema=TriageInput,
)
