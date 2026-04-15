"""
Context assembler for per-window cascade processing.

build_window_context() takes a window_id and the already-scored DataFrame,
merges in the product profile, and computes three derived fields not present
anywhere else in the pipeline:

  delay_ratio       current_delay_min / product's max_excursion_min
  delay_class       negligible (<0.5x) | developing (0.5-1.0x) | critical (>1.0x)
  hours_to_breach   time until avg_temp_c crosses acceptable boundary at current slope
                    None if temperature is stable or heading away from boundary

Also attaches the destination facility record and product cost record so
downstream tools do not need to re-load the data files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Module-level caches — loaded once per process
_facilities: Optional[Dict[str, dict]] = None
_product_costs: Optional[Dict[str, dict]] = None


def _load_facilities() -> Dict[str, dict]:
    global _facilities
    if _facilities is None:
        try:
            from src.supabase_client import load_facilities_with_fallback
            _facilities = load_facilities_with_fallback()
        except Exception:
            with open(_DATA_DIR / "facilities.json") as f:
                _facilities = json.load(f)
    return _facilities


def _load_product_costs() -> Dict[str, dict]:
    global _product_costs
    if _product_costs is None:
        try:
            from src.supabase_client import load_costs_with_fallback
            _product_costs = load_costs_with_fallback()
        except Exception:
            with open(_DATA_DIR / "product_costs.json") as f:
                _product_costs = json.load(f)
    return _product_costs


# ── Derived field calculations ────────────────────────────────────────

def compute_delay_ratio(current_delay_min: float, max_excursion_min: float) -> float:
    """Ratio of current cumulative delay to product's excursion tolerance."""
    if max_excursion_min <= 0:
        return 0.0
    return round(current_delay_min / max_excursion_min, 3)


def compute_delay_class(delay_ratio: float) -> str:
    """
    Classify delay severity relative to the product's excursion tolerance.
      negligible  — delay < 50% of tolerance
      developing  — delay 50–100% of tolerance
      critical    — delay has exceeded tolerance
    """
    if delay_ratio < 0.5:
        return "negligible"
    if delay_ratio < 1.0:
        return "developing"
    return "critical"


def compute_hours_to_breach(
    avg_temp_c: float,
    temp_slope_c_per_hr: float,
    temp_low: float,
    temp_high: float,
) -> Optional[float]:
    """
    Estimate hours until avg_temp_c crosses the nearest acceptable boundary
    at the current rate of temperature change.

    Returns
    -------
    float   hours until breach (0.0 if already outside range)
    None    if temperature is stable (|slope| < 0.05 C/hr), heading away
            from the nearest boundary, or inputs are invalid/unknown
    """
    import math
    if any(math.isnan(v) or math.isinf(v) for v in [avg_temp_c, temp_slope_c_per_hr, temp_low, temp_high]
           if isinstance(v, float)):
        return None

    if temp_low <= -900 or temp_high >= 900:
        return None  # unknown product profile, can't compute meaningful estimate

    already_breached = avg_temp_c < temp_low or avg_temp_c > temp_high
    if already_breached:
        return 0.0

    slope = temp_slope_c_per_hr
    if abs(slope) < 0.05:
        return None

    if slope > 0:
        gap = temp_high - avg_temp_c
        if gap <= 0:
            return 0.0
        return round(gap / slope, 2)

    # slope < 0 — falling toward lower boundary
    gap = avg_temp_c - temp_low
    if gap <= 0:
        return 0.0
    return round(gap / abs(slope), 2)


# ── Main assembler ────────────────────────────────────────────────────

def build_window_context(
    window_id: str,
    df: pd.DataFrame,
    profiles: Dict[str, dict],
) -> Dict[str, Any]:
    """
    Build a fully enriched context object for a single window.

    Parameters
    ----------
    window_id : str
        The window to look up (must exist in df).
    df : pd.DataFrame
        The fully scored DataFrame (output of pipeline.py — includes
        det_score, ml_score, final_score, risk_tier columns).
    profiles : dict
        Product profiles loaded from data/product_profiles.json.

    Returns
    -------
    dict with all raw columns + profile fields + derived cascade fields.
    Raises KeyError if window_id is not found.
    """
    row_df = df[df["window_id"] == window_id]
    if row_df.empty:
        raise KeyError(f"window_id '{window_id}' not found in scored DataFrame")

    row = row_df.iloc[0]
    product_id = str(row["product_id"])
    profile = profiles.get(product_id, {})

    if not profile:
        logger.warning("No product profile for '%s'; using conservative defaults", product_id)

    # ── Core telemetry ────────────────────────────────────────────────
    avg_temp = float(row.get("avg_temp_c", 0.0))
    slope = float(row.get("temp_slope_c_per_hr", 0.0))
    delay = float(row.get("current_delay_min", 0.0))

    # Conservative defaults when profile missing: narrow band triggers alerts
    temp_low = float(profile.get("temp_low", 2.0))
    temp_high = float(profile.get("temp_high", 8.0))
    max_excursion = float(profile.get("max_excursion_min", 30))

    # ── Derived cascade fields ────────────────────────────────────────
    delay_ratio = compute_delay_ratio(delay, max_excursion)
    delay_class = compute_delay_class(delay_ratio)
    hours_to_breach = compute_hours_to_breach(avg_temp, slope, temp_low, temp_high)

    # ── Lookup tables ─────────────────────────────────────────────────
    facilities = _load_facilities()
    product_costs = _load_product_costs()
    facility = facilities.get(product_id, {})
    cost_record = product_costs.get(product_id, {})

    # ── Rules fired as list ───────────────────────────────────────────
    rules_raw = row.get("det_rules_fired", "")
    rules_list = rules_raw.split(";") if isinstance(rules_raw, str) and rules_raw else []

    actions_raw = row.get("recommended_actions", "")
    actions_list = actions_raw.split(";") if isinstance(actions_raw, str) and actions_raw else []

    context: Dict[str, Any] = {
        # Identity
        "window_id": window_id,
        "shipment_id": str(row.get("shipment_id", "")),
        "container_id": str(row.get("container_id", "")),
        "leg_id": str(row.get("leg_id", "")),
        "product_id": product_id,
        "window_start": str(row.get("window_start", "")),
        "window_end": str(row.get("window_end", "")),
        "transit_phase": str(row.get("transit_phase", "")),

        # Raw telemetry
        "avg_temp_c": avg_temp,
        "max_temp_c": float(row.get("max_temp_c", 0.0)),
        "min_temp_c": float(row.get("min_temp_c", 0.0)),
        "temp_slope_c_per_hr": slope,
        "humidity_avg_pct": float(row.get("humidity_avg_pct", 0.0)),
        "shock_count": int(row.get("shock_count", 0)),
        "door_open_count": int(row.get("door_open_count", 0)),
        "minutes_outside_range": int(row.get("minutes_outside_range", 0)),
        "current_delay_min": delay,
        "battery_avg_pct": float(row.get("battery_avg_pct", 0.0)),

        # Risk scores (from pipeline)
        "det_score": round(float(row.get("det_score", 0.0)), 4),
        "ml_score": round(float(row.get("ml_score", 0.0)), 4),
        "final_score": round(float(row.get("final_score", 0.0)), 4),
        "risk_tier": str(row.get("risk_tier", "LOW")),
        "det_rules_fired": rules_list,
        "recommended_actions": actions_list,
        "requires_human_approval": bool(row.get("requires_human_approval", False)),

        # Product profile
        "temp_low": temp_low,
        "temp_high": temp_high,
        "temp_critical_low": float(profile.get("temp_critical_low", -999)),
        "temp_critical_high": float(profile.get("temp_critical_high", 999)),
        "max_excursion_min": max_excursion,
        "humidity_max": float(profile.get("humidity_max", 100)),

        # Derived cascade fields
        "delay_ratio": delay_ratio,
        "delay_class": delay_class,
        "hours_to_breach": hours_to_breach,

        # Lookup data
        "facility": facility,
        "product_cost": cost_record,
    }

    logger.debug(
        "Context assembled: window=%s tier=%s delay_class=%s hours_to_breach=%s",
        window_id, context["risk_tier"], delay_class, hours_to_breach,
    )
    return context
