from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# ── Data loaders ─────────────────────────────────────────────────────

_FACILITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "facilities.json"
_facilities_cache: Optional[dict] = None


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


_COSTS_PATH = Path(__file__).resolve().parent.parent / "data" / "product_costs.json"
_costs_cache: Optional[dict] = None


def _load_product_costs() -> dict:
    global _costs_cache
    if _costs_cache is None:
        try:
            from src.supabase_client import load_costs_with_fallback
            _costs_cache = load_costs_with_fallback()
        except Exception:
            with open(_COSTS_PATH) as f:
                _costs_cache = json.load(f)
    return _costs_cache


# ── Sentinel for missing backup facility ─────────────────────────────

_NO_BACKUP: dict = {
    "feasible": False,
    "routing_reason": "No backup facility on record",
    "advance_notice_hours": 0.0,
    "advance_notice_deficit_hours": 0.0,
    "contact_to_use": "",
    "phone_to_use": "",
    "contact_mode": "standard",
    "capacity_flag": False,
    "capacity_pct": 0,
    "after_hours_flag": False,
    "after_hours_note": "",
}


# ── Input schema ──────────────────────────────────────────────────────

class SchedulingInput(BaseModel):
    shipment_id: str
    product_id: str
    affected_facilities: List[str] = Field(
        description="Hospital/clinic names or codes expecting this shipment"
    )
    original_eta: str = Field(description="Original ETA as ISO datetime string or label")
    revised_eta: Optional[str] = Field(
        default=None,
        description="Revised ETA (ISO datetime), injected by cascade from delay computation",
    )
    reason: str = Field(description="Reason for schedule change")
    # ── Cascade-injected risk context ─────────────────────────────────
    container_id: Optional[str] = Field(
        default=None,
        description="Container identifier for audit traceability (injected by cascade)",
    )
    delay_class: Optional[str] = Field(
        default=None,
        description="Delay severity class from context_assembler: negligible | developing | critical",
    )
    hours_to_breach: Optional[float] = Field(
        default=None,
        description="Estimated hours until temperature breach at current slope; None if stable",
    )
    ml_spoilage_probability: Optional[float] = Field(
        default=None,
        description="ML model spoilage probability (0.0–1.0)",
    )
    risk_tier: Optional[str] = Field(
        default=None,
        description="Risk tier from orchestrator: LOW | MEDIUM | HIGH | CRITICAL",
    )
    advance_notice_required_hours: Optional[float] = Field(
        default=None,
        description="Hours of advance notice the facility requires (cascade-enriched)",
    )
    temp_range_supported: Optional[str] = Field(
        default=None,
        description="Temp range the cold-storage facility supports (cascade-enriched)",
    )


# ── Operating-hours helper ────────────────────────────────────────────

def _parse_any_time_window_open(operating_hours: str, local_dt: datetime) -> bool:
    """Return True if local_dt falls within any HH:MM-HH:MM window in operating_hours."""
    if not operating_hours:
        return True  # no info → assume open
    t_now = local_dt.time()
    for m in re.finditer(r'(\d{2}:\d{2})-(\d{2}:\d{2})', operating_hours):
        open_t  = datetime.strptime(m.group(1), "%H:%M").time()
        close_t = datetime.strptime(m.group(2), "%H:%M").time()
        if open_t <= t_now < close_t:
            return True
    return False


# ── Feasibility helper ────────────────────────────────────────────────

def _check_facility_feasibility(
    facility_record: dict,
    revised_eta_iso: Optional[str],
    now_dt: datetime,
) -> dict:
    """
    Evaluate whether a facility can accept a delivery at the revised ETA.

    Works for both primary and backup records (same field schema).
    Returns a FeasibilityResult dict.
    """
    # 1. Advance notice computation
    if revised_eta_iso:
        try:
            eta_dt = datetime.fromisoformat(revised_eta_iso.replace("Z", "+00:00"))
            advance_notice_hours = max(
                (eta_dt - now_dt).total_seconds() / 3600.0, 0.0
            )
        except (ValueError, TypeError):
            advance_notice_hours = 0.0
    else:
        advance_notice_hours = 0.0

    min_notice = float(facility_record.get("min_advance_notice_hours", 0))
    advance_notice_deficit_hours = advance_notice_hours - min_notice
    notice_ok = advance_notice_deficit_hours >= 0

    # 2. Capacity
    occupancy = int(facility_record.get("current_occupancy_pct", 0))
    capacity_flag = occupancy > 85
    accepts_emergency = facility_record.get("accepts_emergency_delivery", False)

    # 3. After-hours check
    tz_str = facility_record.get("timezone", "UTC")
    try:
        local_dt = now_dt.astimezone(ZoneInfo(tz_str))
    except (ZoneInfoNotFoundError, Exception):
        local_dt = now_dt

    pharmacist_24h = facility_record.get("pharmacist_on_site_24h", False)
    op_hours = facility_record.get("operating_hours", "")
    after_hours_flag = False
    after_hours_note = ""
    if not pharmacist_24h:
        is_open = _parse_any_time_window_open(op_hours, local_dt)
        if not is_open:
            after_hours_flag = True
            after_hours_note = (
                f"Delivery falls outside operating hours ({op_hours}). "
                f"Emergency contact required."
            )

    # 4. Contact selection
    if after_hours_flag or not notice_ok:
        contact_mode = "emergency"
        contact_to_use = facility_record.get(
            "emergency_contact", facility_record.get("contact", "")
        )
        phone_to_use = facility_record.get("emergency_phone", "")
    else:
        contact_mode = "standard"
        contact_to_use = facility_record.get("contact", "")
        phone_to_use = facility_record.get("emergency_phone", "")

    # 5. Overall feasibility — short notice only blocks if emergency delivery is not accepted
    feasible = notice_ok or accepts_emergency

    routing_parts: List[str] = []
    if notice_ok:
        routing_parts.append(
            f"Notice OK ({advance_notice_hours:.1f}h ≥ {min_notice}h required)"
        )
    else:
        if accepts_emergency:
            routing_parts.append(
                f"Short notice ({advance_notice_hours:.1f}h < {min_notice}h required) "
                f"— emergency delivery accepted"
            )
        else:
            routing_parts.append(
                f"INFEASIBLE: {advance_notice_hours:.1f}h notice < {min_notice}h required; "
                f"facility does not accept emergency delivery"
            )
    if capacity_flag:
        routing_parts.append(f"High occupancy ({occupancy}%) — confirm capacity before routing")
    if after_hours_flag:
        routing_parts.append(after_hours_note)

    return {
        "feasible": feasible,
        "routing_reason": "; ".join(routing_parts) or "Feasible",
        "advance_notice_hours": round(advance_notice_hours, 2),
        "advance_notice_deficit_hours": round(advance_notice_deficit_hours, 2),
        "contact_to_use": contact_to_use,
        "phone_to_use": phone_to_use,
        "contact_mode": contact_mode,
        "capacity_flag": capacity_flag,
        "capacity_pct": occupancy,
        "after_hours_flag": after_hours_flag,
        "after_hours_note": after_hours_note,
    }


# ── Priority ranking helper ───────────────────────────────────────────

_MAX_DISRUPTION_USD = 8500.0  # P04 ceiling used for score normalisation


def _rank_appointment_priority(
    product_cost_data: dict,
    hours_to_breach: Optional[float],
) -> dict:
    """
    Compute an appointment priority tier from:
      - downstream_disruption_per_appointment_usd (cost impact)
      - cold_chain_risk_multiplier (product sensitivity)
      - hours_to_breach (urgency amplifier)

    Score = (disruption_usd / 8500) × multiplier × urgency_factor
    Tiers: critical ≥ 2.0 | high ≥ 1.0 | medium ≥ 0.4 | routine < 0.4
    """
    downstream = product_cost_data.get("downstream_impact", {})
    chars = product_cost_data.get("product_characteristics", {})

    disruption_usd = float(
        downstream.get("downstream_disruption_per_appointment_usd", 0.0)
    )
    multiplier = float(chars.get("cold_chain_risk_multiplier", 1.0))
    segments = downstream.get("critical_patient_segments", [])

    if hours_to_breach is not None and hours_to_breach < 4.0:
        urgency_factor = 3.0
        urgency_label = f"breach imminent ({hours_to_breach:.1f}h)"
    elif hours_to_breach is not None and hours_to_breach < 12.0:
        urgency_factor = 2.0
        urgency_label = f"breach within {hours_to_breach:.1f}h"
    else:
        urgency_factor = 1.0
        urgency_label = "stable temperature trend"

    score = round(
        (disruption_usd / _MAX_DISRUPTION_USD) * multiplier * urgency_factor, 4
    )

    if score >= 2.0:
        tier = "critical"
    elif score >= 1.0:
        tier = "high"
    elif score >= 0.4:
        tier = "medium"
    else:
        tier = "routine"

    segments_str = ", ".join(segments) if segments else "general"
    reason = (
        f"${disruption_usd:,.0f}/appointment disruption × "
        f"{multiplier}× risk multiplier × {urgency_factor}× urgency ({urgency_label}); "
        f"critical segments: {segments_str}"
    )

    return {
        "priority_tier": tier,
        "priority_score": score,
        "priority_reason": reason,
    }


# ── Routing resolution helper ─────────────────────────────────────────

def _resolve_facility_routing(
    primary_record: dict,
    backup_record: dict,
    feasibility_primary: dict,
    feasibility_backup: dict,
) -> dict:
    """
    Determine the routing decision from two feasibility results.

    Returns: routing_decision ("primary" | "backup" | "split" | "no_feasible_option")
             routing_summary (human-readable explanation)
    """
    pri_ok = feasibility_primary.get("feasible", False)
    bak_ok = feasibility_backup.get("feasible", False) if backup_record else False

    pri_name = primary_record.get("name", "Primary facility")
    bak_name = backup_record.get("name", "Backup facility") if backup_record else "No backup"

    if not pri_ok and not bak_ok:
        return {
            "routing_decision": "no_feasible_option",
            "routing_summary": (
                f"Neither {pri_name} nor {bak_name} can accept delivery under current "
                f"constraints. Manual escalation required."
            ),
        }

    if pri_ok and bak_ok:
        pri_appt = int(primary_record.get("appointment_count", 0))
        bak_appt = int(backup_record.get("appointment_count", 0) if backup_record else 0)
        # Split when primary is overloaded AND backup has its own patient cohort
        if feasibility_primary.get("capacity_flag", False) and bak_appt > 0:
            return {
                "routing_decision": "split",
                "routing_summary": (
                    f"Split routing: {pri_name} ({pri_appt} appts, high occupancy) + "
                    f"{bak_name} ({bak_appt} appts as overflow)."
                ),
            }
        return {
            "routing_decision": "primary",
            "routing_summary": (
                f"Route to primary: {pri_name}. "
                f"{feasibility_primary.get('routing_reason', '')}"
            ),
        }

    if pri_ok:
        return {
            "routing_decision": "primary",
            "routing_summary": (
                f"Route to primary: {pri_name}. Backup ({bak_name}) not feasible: "
                f"{feasibility_backup.get('routing_reason', '')}"
            ),
        }

    return {
        "routing_decision": "backup",
        "routing_summary": (
            f"Reroute to backup: {bak_name}. Primary ({pri_name}) not feasible: "
            f"{feasibility_primary.get('routing_reason', '')}"
        ),
    }


# ── Main execute function ─────────────────────────────────────────────

def _execute(
    shipment_id: str,
    product_id: str,
    affected_facilities: List[str],
    original_eta: str,
    revised_eta: Optional[str] = None,
    reason: str = "",
    container_id: Optional[str] = None,
    delay_class: Optional[str] = None,
    hours_to_breach: Optional[float] = None,
    ml_spoilage_probability: Optional[float] = None,
    risk_tier: Optional[str] = None,
    advance_notice_required_hours: Optional[float] = None,
    temp_range_supported: Optional[str] = None,
) -> dict:
    # ── Step 1: Load data ─────────────────────────────────────────────
    facilities    = _load_facilities()
    product_costs = _load_product_costs()

    facility_record = facilities.get(product_id, {})
    backup_record   = facility_record.get("backup_facility", {})
    cost_record     = product_costs.get(product_id, {})
    now_dt          = datetime.now(timezone.utc)

    # ── Step 3: Feasibility — primary ────────────────────────────────
    feasibility_primary = _check_facility_feasibility(
        facility_record, revised_eta, now_dt
    )

    # ── Step 4: Feasibility — backup ─────────────────────────────────
    feasibility_backup = (
        _check_facility_feasibility(backup_record, revised_eta, now_dt)
        if backup_record
        else _NO_BACKUP
    )

    # ── Step 5: Routing decision ──────────────────────────────────────
    routing = _resolve_facility_routing(
        facility_record, backup_record or {},
        feasibility_primary, feasibility_backup,
    )
    routing_decision = routing["routing_decision"]
    routing_summary  = routing["routing_summary"]

    # ── Step 6: Appointment priority ─────────────────────────────────
    priority = _rank_appointment_priority(cost_record, hours_to_breach)

    # ── Step 7: Financial impact estimate ────────────────────────────
    downstream = cost_record.get("downstream_impact", {})
    disruption_per_appt = float(
        downstream.get("downstream_disruption_per_appointment_usd", 0.0)
    )
    appointment_count = int(facility_record.get("appointment_count", 0))
    spoilage_prob = float(ml_spoilage_probability or 0.0)
    financial_impact_usd = round(
        disruption_per_appt * appointment_count * spoilage_prob, 2
    )

    # ── Step 8: Compliance flags ──────────────────────────────────────
    compliance_flags: List[str] = []
    for flag in (
        "chain_of_custody_required",
        "regulatory_release_required",
        "patient_registry_required",
        "blood_product_registry_required",
    ):
        if facility_record.get(flag):
            compliance_flags.append(flag)

    # ── Step 9: Select active facility records ────────────────────────
    if routing_decision == "backup":
        active_records = [(backup_record, feasibility_backup)]
    elif routing_decision == "split":
        active_records = [
            (facility_record, feasibility_primary),
            (backup_record, feasibility_backup),
        ]
    else:  # "primary" or "no_feasible_option"
        active_records = [(facility_record, feasibility_primary)]

    # ── Step 10: Build per-facility recommendation dicts ─────────────
    recommendations = []
    for fac_rec, feas in active_records:
        fac_label = fac_rec.get("name", "Unknown")
        fac_loc   = fac_rec.get("location", "")
        appt      = int(fac_rec.get("appointment_count", 0))

        # patient_impact: use priority tier when meaningful, else original heuristic
        if priority["priority_tier"] in ("critical", "high"):
            patient_impact = priority["priority_tier"]
        elif revised_eta and appt >= 10:
            patient_impact = "high"
        else:
            patient_impact = "medium"

        recommendations.append({
            # ── Preserved keys (backward-compatible) ─────────────────
            "facility":          f"{fac_label} ({fac_loc})",
            "facility_contact":  feas["contact_to_use"],
            "action":            "reschedule_appointments",
            "appointment_count": appt,
            "original_eta":      original_eta,
            "revised_eta":       revised_eta or "TBD — awaiting reroute confirmation",
            "patient_impact":    patient_impact,
            "notification_sent": False,
            # ── New additive keys ─────────────────────────────────────
            "facility_id":                fac_rec.get("id", ""),
            "facility_city":              fac_rec.get("city", ""),
            "facility_country":           fac_rec.get("country", ""),
            "airport_code":               fac_rec.get("airport_code", ""),
            "contact_mode":               feas["contact_mode"],
            "phone":                      feas["phone_to_use"],
            "advance_notice_hours":       feas["advance_notice_hours"],
            "advance_notice_deficit_hours": feas["advance_notice_deficit_hours"],
            "capacity_pct":               feas["capacity_pct"],
            "capacity_flag":              feas["capacity_flag"],
            "after_hours_flag":           feas["after_hours_flag"],
            "after_hours_note":           feas["after_hours_note"],
            "feasibility_reason":         feas["routing_reason"],
            "cold_chain_validated":       fac_rec.get("cold_chain_validated_receiving", False),
            "certifications":             fac_rec.get("certifications", []),
        })

    total_appointments = sum(r["appointment_count"] for r in recommendations)

    # ── Step 11: Build actions_required and summary_line ─────────────
    actions_required: List[str] = []

    for flag in compliance_flags:
        actions_required.append(
            f"Verify {flag.replace('_', ' ')} protocol at receiving facility"
        )
    if any(r["after_hours_flag"] for r in recommendations):
        actions_required.append(
            "Use emergency contact — delivery falls outside facility operating hours"
        )
    if routing_decision == "no_feasible_option":
        actions_required.append(
            "ESCALATE: no facility can accept delivery under current constraints"
        )
    if routing_decision in ("backup", "split"):
        actions_required.append(
            "Notify backup facility coordinator to prepare intake"
        )
    if spoilage_prob > 0.5:
        actions_required.append(
            f"High spoilage risk ({spoilage_prob:.0%}): "
            f"prioritise cold-chain handover inspection on arrival"
        )
    if any(r["capacity_flag"] for r in recommendations):
        actions_required.append(
            "Confirm available storage capacity before dispatch — occupancy > 85%"
        )

    replacement = cost_record.get("replacement", {})
    exp_lead = replacement.get("expedited_lead_time_days", "N/A")
    summary_line = (
        f"[{risk_tier or 'N/A'}] {product_id} — {routing_summary} | "
        f"Priority: {priority['priority_tier']} | "
        f"Est. downstream impact: ${financial_impact_usd:,.0f} | "
        f"Replacement lead time: {exp_lead}d expedited"
    )

    # ── Return ────────────────────────────────────────────────────────
    return {
        # Preserved outer keys
        "tool":    "scheduling_agent",
        "status":  "recommendations_generated",
        "shipment_id": shipment_id,
        "product_id":  product_id,
        "reason":      reason,
        "facility_recommendations":    recommendations,
        "total_appointments_affected": total_appointments,
        "note": (
            "This tool generates reschedule recommendations only. "
            "It does not modify EMR or hospital scheduling systems."
        ),
        "requires_approval": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # New additive keys
        "container_id":                container_id or "",
        "routing_decision":            routing_decision,
        "routing_summary":             routing_summary,
        "priority_tier":               priority["priority_tier"],
        "priority_score":              priority["priority_score"],
        "priority_reason":             priority["priority_reason"],
        "financial_impact_estimate_usd": financial_impact_usd,
        "ml_spoilage_probability":     ml_spoilage_probability,
        "delay_class":                 delay_class,
        "hours_to_breach":             hours_to_breach,
        "risk_tier":                   risk_tier,
        "compliance_flags":            compliance_flags,
        "actions_required":            actions_required,
        "summary_line":                summary_line,
        "substitute_available":        replacement.get("substitute_available", False),
        "replacement_lead_time_days":  replacement.get("lead_time_days"),
        "expedited_lead_time_days":    replacement.get("expedited_lead_time_days"),
        # Cascade-provided facility hint (passed through for audit; routing uses facilities.json)
        "cascade_suggested_facilities": affected_facilities,
    }


scheduling_tool = StructuredTool.from_function(
    func=_execute,
    name="scheduling_agent",
    description=(
        "Generate reschedule recommendations for downstream healthcare facilities "
        "affected by shipment delays. Checks feasibility (advance notice, capacity, "
        "operating hours) for both primary and backup facilities, determines routing "
        "decision (primary/backup/split/no_feasible_option), ranks appointment priority "
        "from product cost data, and computes downstream financial impact. "
        "Does NOT directly modify hospital or EMR systems."
    ),
    args_schema=SchedulingInput,
)
