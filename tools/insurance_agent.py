from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
_SCORED_CSV = _BASE / "artifacts" / "scored_windows.csv"
_COSTS_PATH = _BASE / "data" / "product_costs.json"

_scored_df: Optional[pd.DataFrame] = None
_costs_cache: Optional[dict] = None
_FACILITIES_PATH = _BASE / "data" / "facilities.json"
_facilities_cache: Optional[dict] = None


def _load_facilities() -> dict:
    global _facilities_cache
    if _facilities_cache is None:
        with open(_FACILITIES_PATH, encoding='utf-8') as f:
            _facilities_cache = json.load(f)
    return _facilities_cache


def _get_scored_df() -> pd.DataFrame:
    global _scored_df
    if _scored_df is None:
        if not _SCORED_CSV.exists():
            raise FileNotFoundError(
                "scored_windows.csv not found. Run `python pipeline.py train` first."
            )
        _scored_df = pd.read_csv(_SCORED_CSV)
    return _scored_df


def _load_costs() -> dict:
    global _costs_cache
    if _costs_cache is None:
        with open(_COSTS_PATH, encoding='utf-8') as f:
            _costs_cache = json.load(f)
    return _costs_cache


def _aggregate_leg_history(leg_id: str, product_id: str = "") -> Dict[str, Any]:
    """
    Pull all scored windows for a leg and compute excursion metrics.

    Returns a dict with:
      total_excursion_min   sum of minutes_outside_range across the leg
      peak_temp_c           maximum avg_temp_c recorded
      window_count          total windows in the leg
      windows_in_breach     windows where det_score > 0
      breach_timeline       list of {window_id, avg_temp_c, rules_fired}
                            for breached windows (up to 10 most recent)
    """
    df = _get_scored_df()
    leg_df = df[df["leg_id"] == leg_id].copy()

    if leg_df.empty:
        return {
            "leg_id": leg_id,
            "total_excursion_min": 0,
            "peak_temp_c": None,
            "window_count": 0,
            "windows_in_breach": 0,
            "breach_timeline": [],
            "appointment_count": _load_facilities().get(product_id, {}).get("appointment_count", 0),
        }

    total_excursion = int(leg_df["minutes_outside_range"].sum())
    peak_temp = round(float(leg_df["avg_temp_c"].max()), 2)
    window_count = len(leg_df)
    breach_mask = leg_df["det_score"] > 0
    windows_in_breach = int(breach_mask.sum())

    # Most recent 10 breached windows for the evidence timeline
    breached = leg_df[breach_mask].tail(10)
    breach_timeline = [
        {
            "window_id": str(row["window_id"]),
            "avg_temp_c": round(float(row["avg_temp_c"]), 2),
            "rules_fired": str(row.get("det_rules_fired", "")),
        }
        for _, row in breached.iterrows()
    ]

    return {
        "leg_id": leg_id,
        "total_excursion_min": total_excursion,
        "peak_temp_c": peak_temp,
        "window_count": window_count,
        "windows_in_breach": windows_in_breach,
        "breach_timeline": breach_timeline,
        "appointment_count": _load_facilities().get(product_id, {}).get("appointment_count", 0),
    }


def _compute_loss(product_id: str, spoilage_probability: float) -> float:
    """
    Total estimated loss — backward-compatible single float.
    Delegates to _compute_loss_breakdown() and sums all components.
    """
    breakdown = _compute_loss_breakdown(product_id, spoilage_probability)
    return breakdown["total_estimated_loss_usd"]


def _compute_loss_breakdown(
    product_id: str,
    spoilage_probability: float,
    appointment_count: int = 0,
) -> dict:
    """
    Itemised loss estimate across four components:

      product_loss       unit_cost × units × spoilage_prob
      disposal_cost      disposal_per_unit × units × spoilage_prob
      downstream         disruption_per_appointment × appointments × spoilage_prob
      handling_cost      sunk cost — paid regardless of spoilage outcome

    Returns a dict with individual line items and the total.
    """
    costs = _load_costs()
    record = costs.get(product_id, {})
    components = record.get("cost_components", {})
    downstream = record.get("downstream_impact", {})

    unit_cost = float(record.get("unit_cost_usd", 0.0))
    units = int(record.get("units_per_shipment", 0))
    disposal_per_unit = float(components.get("disposal_cost_per_unit_usd", 0.0))
    handling = float(components.get("handling_cost_per_shipment_usd", 0.0))
    disruption_per_appt = float(downstream.get("downstream_disruption_per_appointment_usd", 0.0))
    risk_multiplier = float(
        record.get("product_characteristics", {}).get("cold_chain_risk_multiplier", 1.0)
    )

    product_loss = round(unit_cost * units * spoilage_probability, 2)
    disposal_cost = round(disposal_per_unit * units * spoilage_probability, 2)
    downstream_cost = round(disruption_per_appt * appointment_count * spoilage_probability, 2)
    # Handling is sunk — included in full since it was paid for a shipment that may not deliver
    total = round((product_loss + disposal_cost + downstream_cost + handling) * risk_multiplier, 2)

    return {
        "product_loss_usd": product_loss,
        "disposal_cost_usd": disposal_cost,
        "downstream_disruption_usd": downstream_cost,
        "handling_cost_usd": handling,
        "risk_multiplier": risk_multiplier,
        "total_estimated_loss_usd": total,
    }


class InsuranceInput(BaseModel):
    shipment_id: str
    container_id: str
    product_id: str
    risk_tier: str
    incident_summary: str = Field(description="Brief description of the incident")
    leg_id: Optional[str] = Field(
        default=None,
        description="Leg ID used to aggregate full excursion history from scored data",
    )
    spoilage_probability: Optional[float] = Field(
        default=None,
        description="ML spoilage probability (0-1), used in loss formula",
    )
    estimated_loss_usd: Optional[float] = Field(
        default=None,
        description="Pre-computed loss estimate injected by cascade; computed here if absent",
    )
    supporting_evidence: List[str] = Field(
        default_factory=list,
        description="Compliance log IDs or audit record references",
    )


def _execute(
    shipment_id: str,
    container_id: str,
    product_id: str,
    risk_tier: str,
    incident_summary: str,
    leg_id: Optional[str] = None,
    spoilage_probability: Optional[float] = None,
    estimated_loss_usd: Optional[float] = None,
    supporting_evidence: Optional[List[str]] = None,
) -> dict:
    claim_id = f"CLM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    # Aggregate leg history for the excursion evidence package
    leg_history: Dict[str, Any] = {}
    if leg_id:
        try:
            leg_history = _aggregate_leg_history(leg_id, product_id=product_id)
        except Exception as exc:
            logger.warning("Could not aggregate leg history for %s: %s", leg_id, exc)

    # Compute itemised loss breakdown
    loss_breakdown: Dict[str, Any] = {}
    if spoilage_probability is not None:
        appointment_count = leg_history.get("appointment_count", 0) if leg_history else 0
        loss_breakdown = _compute_loss_breakdown(product_id, spoilage_probability, appointment_count=appointment_count)
        if estimated_loss_usd is None:
            estimated_loss_usd = loss_breakdown["total_estimated_loss_usd"]

    # Pull richer product metadata for the claim package
    costs = _load_costs()
    cost_record = costs.get(product_id, {})
    regulatory_class = cost_record.get("regulatory_class", "")
    therapeutic_area = cost_record.get("therapeutic_area", "")
    replacement = cost_record.get("replacement", {})

    # Build the full excursion summary for the claim
    excursion_summary: Dict[str, Any] = {}
    if leg_history:
        excursion_summary = {
            "total_excursion_min": leg_history.get("total_excursion_min", 0),
            "peak_temp_c": leg_history.get("peak_temp_c"),
            "windows_analysed": leg_history.get("window_count", 0),
            "windows_in_breach": leg_history.get("windows_in_breach", 0),
            "breach_timeline": leg_history.get("breach_timeline", []),
        }

    return {
        "tool": "insurance_agent",
        "status": "claim_draft_prepared",
        "claim_id": claim_id,
        "shipment_id": shipment_id,
        "container_id": container_id,
        "product_id": product_id,
        "product_name": cost_record.get("product_name", product_id),
        "regulatory_class": regulatory_class,
        "therapeutic_area": therapeutic_area,
        "risk_tier": risk_tier,
        "incident_summary": incident_summary,
        "estimated_loss_usd": estimated_loss_usd,
        "loss_breakdown": loss_breakdown,
        "replacement_lead_time_days": replacement.get("lead_time_days"),
        "expedited_lead_time_days": replacement.get("expedited_lead_time_days"),
        "substitute_available": replacement.get("substitute_available", False),
        "excursion_summary": excursion_summary,
        "supporting_evidence": supporting_evidence or [],
        "next_steps": [
            "Attach full audit trail from compliance_agent logs",
            "Obtain QA sign-off on product disposition",
            f"Arrange expedited replacement if lead time ({replacement.get('expedited_lead_time_days', 'TBD')} days) is acceptable",
            "Submit to insurer portal within 72 hours",
        ],
        "requires_approval": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


insurance_tool = StructuredTool.from_function(
    func=_execute,
    name="insurance_agent",
    description=(
        "Prepare insurance claim documentation for a spoilage or excursion "
        "incident. Aggregates the full leg excursion history from scored data, "
        "computes estimated financial loss (unit_cost * units * spoilage_prob), "
        "and packages evidence for human review. Does NOT file the claim."
    ),
    args_schema=InsuranceInput,
)
