"""
Triage Agent — multi-shipment urgency ranking with real data enrichment.

Accepts a list of shipment risk summaries and returns them ranked
by urgency: CRITICAL first, then HIGH, then MEDIUM, then LOW.
Within each tier, higher fused_risk_score ranks first.

Enriches each shipment with real excursion data from scored_windows.csv:
hours at risk, peak temperature, primary breach rule, product name.

Author: Mukul Ray (ray/agents-final), integrated by Rahul
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
_SCORED_CSV = _BASE / "artifacts" / "scored_windows.csv"
_PROFILES_PATH = _BASE / "data" / "product_profiles.json"

_scored_cache: Optional[pd.DataFrame] = None
_profiles_cache: Optional[dict] = None


def _get_scored() -> pd.DataFrame:
    global _scored_cache
    if _scored_cache is None:
        if not _SCORED_CSV.exists():
            return pd.DataFrame()
        _scored_cache = pd.read_csv(_SCORED_CSV)
    return _scored_cache


def _get_profiles() -> dict:
    global _profiles_cache
    if _profiles_cache is None:
        try:
            from src.supabase_client import load_profiles_with_fallback
            _profiles_cache = load_profiles_with_fallback()
        except Exception:
            with open(_PROFILES_PATH) as f:
                _profiles_cache = json.load(f)
    return _profiles_cache


def _enrich_shipment(s: dict) -> dict:
    """
    Pull real context for a shipment from scored_windows.csv.
    Finds the highest-risk window for this shipment and attaches:
      hours_at_risk, peak_temp_c, primary_breach_rule, product_name
    """
    df = _get_scored()
    if df.empty:
        return s

    profiles = _get_profiles()
    shipment_id = s.get("shipment_id", "")
    product_id = s.get("product_id", "")

    sub = df[df["shipment_id"] == shipment_id]
    if sub.empty:
        return s

    breach_windows = sub[sub["det_score"] > 0]
    hours_at_risk = round(len(breach_windows) * 0.5, 1)
    peak_temp = round(float(sub["avg_temp_c"].max()), 2)

    top_rule = ""
    if not breach_windows.empty:
        rules_series = breach_windows["det_rules_fired"].dropna()
        if not rules_series.empty:
            all_rules = ";".join(rules_series.astype(str)).split(";")
            all_rules = [r.strip() for r in all_rules if r.strip()]
            if all_rules:
                top_rule = Counter(all_rules).most_common(1)[0][0]

    profile = profiles.get(product_id, {})
    product_name = profile.get("name", product_id)

    enriched = dict(s)
    enriched["hours_at_risk"] = hours_at_risk
    enriched["peak_temp_c"] = peak_temp
    enriched["primary_breach_rule"] = top_rule
    enriched["product_name"] = product_name
    enriched["total_windows"] = len(sub)
    enriched["windows_in_breach"] = len(breach_windows)
    return enriched


class ShipmentRiskSummary(BaseModel):
    shipment_id: str
    risk_tier: str
    fused_risk_score: float
    product_id: str
    container_id: Optional[str] = Field(default="")
    transit_phase: Optional[str] = Field(default="")


class TriageInput(BaseModel):
    shipments: List[ShipmentRiskSummary] = Field(
        description="List of shipments with their current risk data"
    )
    enrich: bool = Field(
        default=True,
        description="If True, pull real excursion context from scored data for each shipment"
    )


def _execute(
    shipments: List[Any],
    enrich: bool = True,
) -> dict:
    tier_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    items = [
        s.model_dump() if hasattr(s, "model_dump") else dict(s)
        for s in shipments
    ]

    if enrich and _SCORED_CSV.exists():
        enriched_items = []
        for item in items:
            try:
                enriched_items.append(_enrich_shipment(item))
            except Exception as exc:
                logger.warning("Enrichment failed for %s: %s", item.get("shipment_id"), exc)
                enriched_items.append(item)
        items = enriched_items

    ranked = sorted(
        items,
        key=lambda s: (
            tier_order.get(s.get("risk_tier", "LOW"), 3),
            -s.get("fused_risk_score", 0),
        ),
    )

    priority_list = []
    for rank, s in enumerate(ranked, 1):
        tier = s.get("risk_tier", "LOW")
        score = s.get("fused_risk_score", 0.0)

        if tier == "CRITICAL":
            urgency_label = "Immediate action required"
        elif tier == "HIGH":
            urgency_label = "Intervene within 1 hour"
        elif tier == "MEDIUM":
            urgency_label = "Monitor closely"
        else:
            urgency_label = "Standard monitoring"

        priority_list.append({
            "priority_rank": rank,
            "shipment_id": s.get("shipment_id", ""),
            "container_id": s.get("container_id", ""),
            "risk_tier": tier,
            "fused_risk_score": round(score, 4),
            "product_id": s.get("product_id", ""),
            "product_name": s.get("product_name", s.get("product_id", "")),
            "transit_phase": s.get("transit_phase", ""),
            "needs_immediate_attention": tier in ("CRITICAL", "HIGH"),
            "urgency_label": urgency_label,
            "hours_at_risk": s.get("hours_at_risk"),
            "peak_temp_c": s.get("peak_temp_c"),
            "primary_breach_rule": s.get("primary_breach_rule", ""),
            "windows_in_breach": s.get("windows_in_breach"),
            "total_windows": s.get("total_windows"),
        })

    critical_count = sum(1 for s in ranked if s.get("risk_tier") == "CRITICAL")
    high_count = sum(1 for s in ranked if s.get("risk_tier") == "HIGH")

    return {
        "tool": "triage_agent",
        "status": "ranked",
        "total_shipments": len(ranked),
        "critical_count": critical_count,
        "high_count": high_count,
        "shipments_requiring_action": critical_count + high_count,
        "priority_list": priority_list,
        "recommended_orchestration_order": [
            item["shipment_id"]
            for item in priority_list
            if item["needs_immediate_attention"]
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


triage_tool = StructuredTool.from_function(
    func=_execute,
    name="triage_agent",
    description=(
        "Rank multiple at-risk shipments by urgency before orchestration. "
        "Returns a priority-ordered list with CRITICAL and HIGH flagged for "
        "immediate attention. Enriches each shipment with real excursion data "
        "(hours at risk, peak temp, primary breach rule) from scored history. "
        "Use recommended_orchestration_order to decide which shipments to pass "
        "to the orchestrator first."
    ),
    args_schema=TriageInput,
)
