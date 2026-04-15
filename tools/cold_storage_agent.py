from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.data_loader import load_product_profiles


_FACILITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "facilities.json"
_PROFILES_PATH   = Path(__file__).resolve().parent.parent / "data" / "product_profiles.json"

_facilities_cache: Optional[dict] = None
_profiles_cache:   Optional[dict] = None


def _load_facilities() -> dict:
    global _facilities_cache
    if _facilities_cache is None:
        try:
            from src.supabase_client import load_facilities_with_fallback
            _facilities_cache = load_facilities_with_fallback()
        except Exception:
            with open(_FACILITIES_PATH) as f:
                _facilities_cache = json.load(f)
    return _facilities_cache


def _load_profiles() -> dict:
    global _profiles_cache
    if _profiles_cache is None:
        try:
            from src.supabase_client import load_profiles_with_fallback
            _profiles_cache = load_profiles_with_fallback()
        except Exception:
            _profiles_cache = load_product_profiles(_PROFILES_PATH)
    return _profiles_cache


class ColdStorageInput(BaseModel):
    shipment_id: str = Field(description="Shipment needing cold storage")
    container_id: str = Field(description="Container ID")
    product_id: str = Field(description="Product type for temp matching")
    location_hint: Optional[str] = Field(
        default=None, description="Nearest airport/city code"
    )
    urgency: str = Field(
        default="high", description="low, medium, high, or critical"
    )
    hours_to_breach: Optional[float] = Field(
        default=None, description="Hours until temp breach at current slope"
    )
    avg_temp_c: Optional[float] = Field(
        default=None, description="Current average container temp °C"
    )
    temp_slope_c_per_hr: Optional[float] = Field(
        default=None, description="Temperature trend slope °C/hr"
    )


def _parse_temp_range(range_str: str) -> tuple:
    """
    Parse a temp_range_supported string into a (low, high) float tuple.

    Handles:
      "2-8C"         -> (2.0, 8.0)
      "15-25C"       -> (15.0, 25.0)
      "-80C to -15C" -> (-80.0, -15.0)
      "-80C to -20C" -> (-80.0, -20.0)
    """
    norm = range_str.upper().strip()

    # Pass 1: "TO"-separated (handles negative values)
    if "TO" in norm:
        try:
            parts = norm.split("TO")
            low  = float(parts[0].replace("C", "").strip())
            high = float(parts[1].replace("C", "").strip())
            return (low, high)
        except (ValueError, IndexError):
            pass

    # Pass 2: dash-separated positive values (e.g. "2-8C", "15-25C")
    if not norm.startswith("-"):
        try:
            stripped = norm.replace("C", "").strip()
            parts = stripped.split("-")
            low  = float(parts[0].strip())
            high = float(parts[1].strip())
            return (low, high)
        except (ValueError, IndexError):
            pass

    # Pass 3: regex fallback
    try:
        nums = re.findall(r"-?\d+(?:\.\d+)?", range_str)
        if len(nums) >= 2:
            return (float(nums[0]), float(nums[1]))
    except (ValueError, IndexError):
        pass

    return (-999.0, 999.0)


def _check_temp_compatibility(facility_record: dict, product_id: str, profiles: dict) -> dict:
    """
    Hard gate: facility is compatible iff fac_low <= prod_low AND fac_high >= prod_high.
    """
    fac_range_str = facility_record.get("temp_range_supported", "")
    fac_low, fac_high = _parse_temp_range(fac_range_str) if fac_range_str else (-999.0, 999.0)

    profile  = profiles.get(product_id, {})
    prod_low = float(profile.get("temp_low",  -999.0))
    prod_high = float(profile.get("temp_high",  999.0))

    compatible = (fac_low <= prod_low) and (fac_high >= prod_high)

    note = (
        f"Facility supports {fac_range_str} ({fac_low}–{fac_high}°C); "
        f"product {product_id} requires {prod_low}–{prod_high}°C. "
        + ("Compatible." if compatible else "Incompatible: range mismatch.")
    )

    return {
        "compatible": compatible,
        "facility_range": (fac_low, fac_high),
        "required_range": (prod_low, prod_high),
        "compatibility_note": note,
    }


def _score_facility(
    facility_record: dict,
    product_id: str,
    location_hint: Optional[str],
    hours_to_breach: Optional[float],
    urgency: str,
    profiles: dict,
) -> dict:
    """
    Score a single facility candidate.  Returns score fields that are merged
    onto the facility_record dict in _build_candidate_list().
    """
    # Hard gate 1: temperature compatibility
    temp_compat = _check_temp_compatibility(facility_record, product_id, profiles)
    if not temp_compat["compatible"]:
        return {
            "suitability_score": 0.0,
            "suitability_tier": "disqualified",
            "suitability_reason": "Temperature range incompatible with product requirements.",
            "disqualified": True,
            "disqualification_reason": "temperature_incompatible",
            "temp_compatibility": temp_compat,
        }

    # Hard gate 2: emergency delivery
    if urgency == "critical" and not facility_record.get("accepts_emergency_delivery", False):
        return {
            "suitability_score": 0.0,
            "suitability_tier": "disqualified",
            "suitability_reason": "Facility does not accept emergency deliveries.",
            "disqualified": True,
            "disqualification_reason": "no_emergency_delivery",
            "temp_compatibility": temp_compat,
        }

    # Sub-score: capacity
    occupancy_pct  = float(facility_record.get("current_occupancy_pct", 50))
    capacity_score = (100.0 - occupancy_pct) / 100.0
    # Urgency amplifier (mirrors scheduling_agent priority logic)
    if hours_to_breach is not None and hours_to_breach < 4.0:
        capacity_score = min(capacity_score * 1.5, 1.0)

    # Sub-score: proximity
    airport_code       = facility_record.get("airport_code", "").upper()
    city               = facility_record.get("city", "").upper()
    location_str       = facility_record.get("location", "").upper()
    hint               = (location_hint or "").upper().strip()

    if hint and airport_code == hint:
        proximity_score = 1.0
    elif hint and (hint in city or city in hint or hint in location_str):
        proximity_score = 0.5
    else:
        proximity_score = 0.0

    # Sub-score: advance notice window
    min_notice = float(facility_record.get("min_advance_notice_hours", 0))
    if hours_to_breach is not None and min_notice > 0:
        notice_score = min(hours_to_breach / min_notice, 1.0)
    else:
        notice_score = 1.0  # no breach horizon → assume sufficient lead time

    # Sub-score: certifications
    certs     = facility_record.get("certifications", [])
    cert_score = min(0.5 + (len(certs) - 1) * 0.1, 1.0) if certs else 0.0

    # Composite
    composite = (
        0.4 * capacity_score
        + 0.3 * proximity_score
        + 0.2 * notice_score
        + 0.1 * cert_score
    )

    if composite >= 0.75:
        tier = "ideal"
    elif composite >= 0.50:
        tier = "good"
    elif composite >= 0.25:
        tier = "acceptable"
    else:
        tier = "last_resort"

    reason = (
        f"Capacity={capacity_score:.2f}(×0.4), "
        f"Proximity={proximity_score:.2f}(×0.3), "
        f"Notice={notice_score:.2f}(×0.2), "
        f"Certs={cert_score:.2f}(×0.1) → {composite:.3f} ({tier})"
    )

    return {
        "suitability_score": round(composite, 4),
        "suitability_tier": tier,
        "suitability_reason": reason,
        "disqualified": False,
        "disqualification_reason": "",
        "temp_compatibility": temp_compat,
    }


def _build_candidate_list(
    product_id: str,
    location_hint: Optional[str],
    hours_to_breach: Optional[float],
    urgency: str,
    profiles: dict,
) -> list:
    """
    Load primary + backup facility records for product_id, score each,
    and return sorted list (viable first, then by descending score).
    """
    facs = _load_facilities()
    product_fac = facs.get(product_id)
    if not product_fac:
        return []

    # Primary: all keys except the nested backup_facility block
    primary_record = {k: v for k, v in product_fac.items() if k != "backup_facility"}
    primary_record["_candidate_role"] = "primary"
    primary_scores = _score_facility(
        primary_record, product_id, location_hint, hours_to_breach, urgency, profiles
    )
    candidates = [{**primary_record, **primary_scores}]

    # Backup (optional)
    backup_raw = product_fac.get("backup_facility")
    if backup_raw:
        backup_record = dict(backup_raw)
        backup_record["_candidate_role"] = "backup"
        backup_scores = _score_facility(
            backup_record, product_id, location_hint, hours_to_breach, urgency, profiles
        )
        candidates.append({**backup_record, **backup_scores})

    # Viable first, then by descending suitability score
    candidates.sort(key=lambda c: (c.get("disqualified", False), -c.get("suitability_score", 0.0)))
    return candidates


def _execute(
    shipment_id: str,
    container_id: str,
    product_id: str,
    location_hint: Optional[str] = None,
    urgency: str = "high",
    hours_to_breach: Optional[float] = None,
    avg_temp_c: Optional[float] = None,
    temp_slope_c_per_hr: Optional[float] = None,
) -> dict:
    profiles   = _load_profiles()
    candidates = _build_candidate_list(
        product_id, location_hint, hours_to_breach, urgency, profiles
    )

    all_disqualified = bool(candidates) and all(
        c.get("disqualified", False) for c in candidates
    )

    primary_rec   = candidates[0] if candidates else {}
    alt_facilities = candidates[1:] if len(candidates) > 1 else []

    # Status
    if not candidates:
        status = "no_facility_data"
    elif all_disqualified:
        status = "no_qualified_facility"
    else:
        status = "facility_identified"

    # Transfer window: 80% of hours_to_breach (20% safety margin before breach)
    transfer_window_hours = (
        round(hours_to_breach * 0.8, 2) if hours_to_breach is not None else None
    )

    # Compliance flags from primary facility record
    compliance_flags: dict = {}
    for flag_key in (
        "chain_of_custody_required",
        "regulatory_release_required",
        "patient_registry_required",
        "blood_product_registry_required",
    ):
        val = primary_rec.get(flag_key)
        if val:
            compliance_flags[flag_key] = val

    # Selection rationale
    suitability_reason = primary_rec.get("suitability_reason", "")
    if all_disqualified:
        selection_rationale = (
            f"WARNING: All candidate facilities disqualified. "
            f"Best available (disqualified): {primary_rec.get('name', 'unknown')}. "
            f"Reason: {primary_rec.get('disqualification_reason', 'unknown')}. "
            f"{suitability_reason}"
        )
    elif not candidates:
        selection_rationale = f"No facility data found for product_id={product_id}."
    else:
        selection_rationale = (
            f"Selected: {primary_rec.get('name', 'unknown')} "
            f"(score={primary_rec.get('suitability_score', 0.0):.3f}, "
            f"tier={primary_rec.get('suitability_tier', 'unknown')}). "
            f"{suitability_reason}"
        )

    # Alternative facilities — slim dicts for downstream consumers
    alt_list = [
        {
            "id":                          a.get("id", ""),
            "name":                        a.get("name", ""),
            "location":                    a.get("location", ""),
            "airport_code":                a.get("airport_code", ""),
            "suitability_score":           a.get("suitability_score", 0.0),
            "suitability_tier":            a.get("suitability_tier", ""),
            "available_capacity_pct":      100 - float(a.get("current_occupancy_pct", 50)),
            "temp_range_supported":        a.get("temp_range_supported", ""),
            "advance_notice_required_hours": a.get("min_advance_notice_hours"),
            "disqualified":                a.get("disqualified", False),
            "disqualification_reason":     a.get("disqualification_reason", ""),
        }
        for a in alt_facilities
    ]

    return {
        # ── Preserved outer keys (notification_agent + scheduling_agent read these) ──
        "tool":                   "cold_storage_agent",
        "status":                 status,
        "shipment_id":            shipment_id,
        "container_id":           container_id,
        "product_id":             product_id,
        "recommended_facility":   primary_rec.get("name", ""),
        "location":               primary_rec.get("location", ""),
        "available_capacity_pct": 100 - float(primary_rec.get("current_occupancy_pct", 50)),
        "temp_range":             primary_rec.get("temp_range_supported", ""),
        "urgency":                urgency,
        "requires_approval":      True,
        "timestamp":              datetime.now(timezone.utc).isoformat(),
        # ── New additive keys ──
        "recommended_facility_id":       primary_rec.get("id", ""),
        "temp_range_supported":          primary_rec.get("temp_range_supported", ""),
        "certifications":                primary_rec.get("certifications", []),
        "contact":                       primary_rec.get("contact", ""),
        "emergency_phone":               primary_rec.get("emergency_phone", ""),
        "advance_notice_required_hours": primary_rec.get("min_advance_notice_hours"),
        "transfer_window_hours":         transfer_window_hours,
        "suitability_score":             primary_rec.get("suitability_score", 0.0),
        "suitability_tier":              primary_rec.get("suitability_tier", ""),
        "alternative_facilities":        alt_list,
        "selection_rationale":           selection_rationale,
        "compliance_flags":              compliance_flags,
        "temp_compatibility":            primary_rec.get("temp_compatibility", {}),
        "all_candidates_disqualified":   all_disqualified,
        "avg_temp_c":                    avg_temp_c,
        "temp_slope_c_per_hr":           temp_slope_c_per_hr,
        "hours_to_breach":               hours_to_breach,
    }


cold_storage_tool = StructuredTool.from_function(
    func=_execute,
    name="cold_storage_agent",
    description=(
        "Find and recommend a backup cold-storage facility near the "
        "shipment's current location.  Scores candidates from facilities.json "
        "using temperature compatibility, proximity, capacity, and advance notice "
        "constraints.  Returns facility details, suitability score, and alternatives. "
        "Does NOT reserve; requires approval."
    ),
    args_schema=ColdStorageInput,
)
