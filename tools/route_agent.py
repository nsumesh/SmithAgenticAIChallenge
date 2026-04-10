"""
Route Agent — context-aware route recommendation.

Selects an alternative route based on:
  - product temperature class (frozen / refrigerated / CRT)
  - preferred_mode if specified
  - reason/urgency signal

Output dict keys are unchanged from the original so the orchestrator
cascade (_enrich_tool_input in nodes.py) continues to work without
modification.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
_PROFILES_PATH = _BASE / "data" / "product_profiles.json"

_profiles_cache: Optional[dict] = None


def _load_profiles() -> dict:
    global _profiles_cache
    if _profiles_cache is None:
        with open(_PROFILES_PATH) as f:
            _profiles_cache = json.load(f)
    return _profiles_cache


def _get_temp_class(product_id: str) -> str:
    """
    Returns one of: 'frozen', 'refrigerated', 'crt'
    based on the product's safe temp range from product_profiles.json.
    """
    profiles = _load_profiles()
    profile = profiles.get(product_id, {})
    temp_low = float(profile.get("temp_low", 2))
    temp_high = float(profile.get("temp_high", 8))

    if temp_high <= 0:
        return "frozen"
    if temp_high <= 15:
        return "refrigerated"
    return "crt"


# Routes keyed by temp_class then preferred_mode.
# Each entry: (route_string, carrier, eta_delta_hours)
# eta_delta_hours negative = faster than original.
_ROUTE_TABLE = {
    "frozen": {
        "air": [
            ("ANC→ORD (air, ultra-cold certified)", "Atlas Air Cold Chain", -5),
            ("FRA→JFK (air, dry-ice certified)", "Cargolux CoolChain", -4),
        ],
        "road": [
            ("Chicago→NYC (cryogenic road freight)", "Cold Chain Direct", 2),
        ],
        "default": [
            ("ANC→ORD (air, ultra-cold certified)", "Atlas Air Cold Chain", -5),
            ("FRA→JFK (air, dry-ice certified)", "Cargolux CoolChain", -4),
        ],
    },
    "refrigerated": {
        "air": [
            ("LHR→JFK (air, 2-8C certified)", "British Airways World Cargo", -3),
            ("AMS→ORD (air, pharma lane)", "KLM Cargo CoolCenter", -2),
            ("FRA→MIA (air, GDP-certified)", "Lufthansa Cargo td.Pharma", -4),
        ],
        "road": [
            ("Hub→Destination (GDP road, active reefer)", "DHL Life Sciences", 1),
            ("Regional depot relay (passive PCM box)", "Marken Road", 3),
        ],
        "default": [
            ("LHR→JFK (air, 2-8C certified)", "British Airways World Cargo", -3),
            ("AMS→ORD (air, pharma lane)", "KLM Cargo CoolCenter", -2),
        ],
    },
    "crt": {
        "air": [
            ("CDG→MIA (air standard)", "Air France Cargo", -1),
            ("LHR→ORD (air standard)", "Virgin Atlantic Cargo", -2),
        ],
        "road": [
            ("Hub→Destination (insulated road freight)", "UPS Healthcare", 2),
            ("Regional relay (ambient controlled)", "FedEx Custom Critical", 1),
        ],
        "default": [
            ("CDG→MIA (air standard)", "Air France Cargo", -1),
            ("LHR→ORD (air standard)", "Virgin Atlantic Cargo", -2),
        ],
    },
}


def _select_route(temp_class: str, preferred_mode: Optional[str], reason: str) -> dict:
    """
    Pick the best route entry from _ROUTE_TABLE given temp_class and mode.
    Falls back to 'default' mode bucket if preferred_mode is not in the table.
    Picks index 0 (best option) unless reason contains 'urgent' or 'critical',
    in which case it also prefers index 0 (fastest ETA delta).
    """
    class_routes = _ROUTE_TABLE.get(temp_class, _ROUTE_TABLE["refrigerated"])

    mode_key = "default"
    if preferred_mode and preferred_mode.lower() in class_routes:
        mode_key = preferred_mode.lower()

    options = class_routes[mode_key]

    # For urgent/critical reasons prefer the option with the most negative eta_delta
    reason_lower = reason.lower()
    if any(word in reason_lower for word in ("urgent", "critical", "immediate", "emergency")):
        options = sorted(options, key=lambda x: x[2])  # sort by eta_delta ascending (most negative first)

    route_str, carrier, eta_delta = options[0]
    return {
        "recommended_route": route_str,
        "carrier": carrier,
        "eta_change_hours": eta_delta,
    }


class RouteInput(BaseModel):
    shipment_id: str = Field(description="Shipment to reroute")
    container_id: str = Field(description="Container within the shipment")
    current_leg_id: str = Field(description="Current transport leg")
    reason: str = Field(description="Why rerouting is requested")
    product_id: Optional[str] = Field(
        default=None,
        description="Product ID (e.g. P01, P04) — used to select temp-class appropriate route",
    )
    preferred_mode: Optional[str] = Field(
        default=None,
        description="Preferred transport mode: air, road, or None for auto",
    )


def _execute(
    shipment_id: str,
    container_id: str,
    current_leg_id: str,
    reason: str,
    product_id: Optional[str] = None,
    preferred_mode: Optional[str] = None,
) -> dict:
    temp_class = _get_temp_class(product_id) if product_id else "refrigerated"
    route = _select_route(temp_class, preferred_mode, reason)

    logger.info(
        "route_agent: shipment=%s product=%s temp_class=%s → %s",
        shipment_id, product_id, temp_class, route["recommended_route"],
    )

    return {
        "tool": "route_agent",
        "status": "recommendation_generated",
        "shipment_id": shipment_id,
        "container_id": container_id,
        "original_leg": current_leg_id,
        "recommended_route": route["recommended_route"],
        "carrier": route["carrier"],
        "eta_change_hours": route["eta_change_hours"],
        "temp_class": temp_class,
        "reason": reason,
        "requires_approval": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


route_tool = StructuredTool.from_function(
    func=_execute,
    name="route_agent",
    description=(
        "Recommend an alternative route or carrier for a shipment. "
        "Selects route based on product temperature class (frozen/refrigerated/CRT) "
        "and preferred transport mode. Returns a route option with ETA impact. "
        "Does NOT auto-execute; requires human approval."
    ),
    args_schema=RouteInput,
)
