"""
Route Agent — context-aware route recommendation with live weather and LLM reasoning.

Pipeline:
1. Classify product temperature class from product_profiles.json
   (frozen / refrigerated / CRT)
2. Fetch live weather at destination facility via Open-Meteo
   (free, no API key, lat/lon from facility record)
3. Call Groq LLM with full shipment context to reason about
   the best route and carrier — not a lookup table
4. Return structured recommendation with natural language justification

Output dict keys are unchanged from the original so the orchestrator
cascade (_enrich_tool_input in nodes.py) continues to work.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from groq import Groq
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
    based on the product's safe temp range.
    """
    profiles = _load_profiles()
    profile = profiles.get(product_id, {})
    temp_high = float(profile.get("temp_high", 8))
    if temp_high <= 0:
        return "frozen"
    if temp_high <= 15:
        return "refrigerated"
    return "crt"


def _get_product_info(product_id: str) -> dict:
    """Return human-readable product details for the LLM prompt."""
    profiles = _load_profiles()
    p = profiles.get(product_id, {})
    return {
        "name": p.get("name", product_id),
        "temp_low": p.get("temp_low", 2),
        "temp_high": p.get("temp_high", 8),
        "temp_critical_low": p.get("temp_critical_low", -999),
        "temp_critical_high": p.get("temp_critical_high", 999),
        "max_excursion_min": p.get("max_excursion_min", 60),
        "freeze_sensitive": p.get("freeze_sensitive", False),
    }


# Weather code to human description mapping (WMO codes)
_WMO_DESCRIPTIONS = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow",
    80: "light showers", 81: "moderate showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

# Severe weather codes that genuinely affect air/road freight
_SEVERE_WEATHER_CODES = {65, 75, 82, 86, 95, 96, 99}


def _fetch_weather(facility: dict) -> dict:
    """
    Fetch current weather at the destination facility using Open-Meteo.
    Free, no API key required. Falls back gracefully if unavailable.

    Returns a dict with weather context for the LLM.
    """
    # Try to get coordinates from facility record
    # facilities.json has city field (e.g. "London") and location string
    # (e.g. "London Heathrow (LHR)") — prefer city for reliable matching
    city_str = facility.get("city", "").lower()
    location_str = facility.get("location", "").lower()
    search_str = city_str if city_str else location_str
    facility_name = facility.get("name", "unknown facility")

    # Map known facility locations to coordinates
    # These match the facilities.json data for P01-P06
    location_coords = {
        "london": (51.477, -0.461),       # LHR area
        "birmingham": (52.453, -1.748),   # BHX area
        "manchester": (53.365, -2.273),   # MAN area
        "edinburgh": (55.950, -3.372),    # EDI area
        "glasgow": (55.862, -4.252),
        "amsterdam": (52.310, 4.768),     # AMS
        "frankfurt": (50.033, 8.571),     # FRA
        "paris": (49.009, 2.548),         # CDG
        "new york": (40.641, -73.778),    # JFK
        "chicago": (41.974, -87.907),     # ORD
    }

    lat, lon = 51.477, -0.461  # default to LHR if unknown
    for city, coords in location_coords.items():
        if city in search_str:
            lat, lon = coords
            break

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,wind_speed_10m,precipitation,weather_code"
            f"&wind_speed_unit=mph&timezone=auto"
        )
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        current = data["current"]

        code = current.get("weather_code", 0)
        description = _WMO_DESCRIPTIONS.get(code, f"weather code {code}")
        is_severe = code in _SEVERE_WEATHER_CODES

        return {
            "facility_name": facility_name,
            "location": location_str,
            "temperature_c": current.get("temperature_2m"),
            "wind_speed_mph": current.get("wind_speed_10m"),
            "precipitation_mm": current.get("precipitation"),
            "weather_description": description,
            "is_severe_weather": is_severe,
            "weather_code": code,
            "data_source": "Open-Meteo live",
        }

    except Exception as exc:
        logger.warning("Open-Meteo fetch failed for %s: %s", facility_name, exc)
        return {
            "facility_name": facility_name,
            "location": location_str,
            "temperature_c": None,
            "wind_speed_mph": None,
            "precipitation_mm": None,
            "weather_description": "weather data unavailable",
            "is_severe_weather": False,
            "weather_code": None,
            "data_source": "unavailable",
        }


def _call_groq_for_route(
    shipment_id: str,
    product_id: str,
    temp_class: str,
    product_info: dict,
    reason: str,
    preferred_mode: Optional[str],
    weather: dict,
    risk_context: dict,
) -> dict:
    """
    Call Groq LLM to reason about the best route recommendation.
    Returns a dict with recommended_route, carrier, eta_change_hours, justification.

    Falls back to a deterministic safe option if the API call fails.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")

    # Build rich context for the LLM
    weather_summary = (
        f"{weather['weather_description']} at {weather['facility_name']}"
        f" ({weather['location']})"
    )
    if weather["temperature_c"] is not None:
        weather_summary += f", {weather['temperature_c']}°C"
    if weather["wind_speed_mph"] is not None:
        weather_summary += f", wind {weather['wind_speed_mph']}mph"
    if weather["is_severe_weather"]:
        weather_summary += " — SEVERE WEATHER ALERT"

    rules_fired = risk_context.get("det_rules_fired", [])
    hours_to_breach = risk_context.get("hours_to_breach")
    delay_class = risk_context.get("delay_class", "unknown")
    avg_temp = risk_context.get("avg_temp_c")
    temp_slope = risk_context.get("temp_slope_c_per_hr")
    transit_phase = risk_context.get("transit_phase", "unknown")
    risk_tier = risk_context.get("risk_tier", "CRITICAL")

    hours_str = f"{hours_to_breach:.1f} hours" if hours_to_breach is not None else "already breached"

    already_breached = hours_to_breach == 0.0 or hours_to_breach is None
    urgency_instruction = (
        "CRITICAL: Product is already in temperature excursion. "
        "Prioritise the FASTEST certified option regardless of cost. "
        "ETA change must be negative (faster than current route)."
        if already_breached and risk_tier == "CRITICAL"
        else "Choose the best balance of speed and cold chain certification."
    )

    prompt = f"""You are a pharmaceutical cold chain logistics specialist making an emergency rerouting decision.

IMPORTANT: You are recommending a CARRIER and TRANSPORT MODE for this shipment — not inventing a geographic route. The destination facility is fixed. Focus on which certified carrier can reach the destination fastest with the correct temperature controls.

SHIPMENT:
- ID: {shipment_id}
- Product: {product_info.get('name', product_id)} ({product_id})
- Temperature class: {temp_class.upper()} — must maintain {product_info.get('temp_low', 2)}°C to {product_info.get('temp_high', 8)}°C
- Freeze sensitive: {product_info.get('freeze_sensitive', False)}
- Max allowed excursion: {product_info.get('max_excursion_min', 60)} min
- Risk tier: {risk_tier}
- Transit phase: {transit_phase}

CURRENT BREACH STATUS:
- Container temperature: {avg_temp}°C (slope: {temp_slope}°C/hr)
- Time until breach: {hours_str}
- Delay severity: {delay_class}
- Active rules: {', '.join(rules_fired) if rules_fired else 'none'}
- Reason: {reason}

DESTINATION:
- Facility: {weather.get('facility_name', 'unknown')} ({weather.get('location', 'unknown')})
- Current weather there: {weather_summary}

PREFERRED MODE: {preferred_mode if preferred_mode else 'choose best mode for this situation'}

URGENCY GUIDANCE: {urgency_instruction}

For temperature class guidance:
- FROZEN (-25 to -15°C): requires dry-ice or cryogenic-certified air freight (Atlas Air, Cargolux, Lufthansa Cargo)
- REFRIGERATED (2-8°C): requires GDP-certified pharma lane (British Airways World Cargo, DHL Life Sciences, Marken)
- CRT (10-25°C): standard temperature-controlled freight (DHL, FedEx Custom Critical, UPS Healthcare)

Respond ONLY with valid JSON, no other text:
{{
  "recommended_route": "transport mode and key hub description, e.g. Air freight via LHR (GDP-certified pharma lane)",
  "carrier": "specific carrier name with relevant certification",
  "eta_change_hours": <integer — MUST be negative for CRITICAL already-breached shipments>,
  "justification": "2-3 sentences explaining why this carrier and mode given the specific breach status, product requirements, and weather conditions"
}}"""

    # Fallback routes by temp class in case API fails
    fallback_routes = {
        "frozen": ("ANC->ORD (air, ultra-cold certified)", "Atlas Air Cold Chain", -5),
        "refrigerated": ("LHR->JFK (air, 2-8C GDP certified)", "British Airways World Cargo", -3),
        "crt": ("CDG->MIA (air standard)", "Air France Cargo", -1),
    }

    if not api_key or api_key == "your_key_here":
        logger.warning("No Groq API key set — using deterministic fallback")
        route, carrier, eta = fallback_routes.get(temp_class, fallback_routes["refrigerated"])
        return {
            "recommended_route": route,
            "carrier": carrier,
            "eta_change_hours": eta,
            "justification": f"Deterministic fallback: {temp_class} product routed via certified carrier. Set GROQ_API_KEY in .env for LLM reasoning.",
            "reasoning_source": "deterministic_fallback",
        }

    try:
        client = Groq(api_key=api_key)

        # Try primary model, fall back to mixtral if rate limited
        primary_model = "llama-3.3-70b-versatile"
        fallback_model = "llama-3.1-8b-instant"

        try:
            response = client.chat.completions.create(
                model=primary_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=600,
                timeout=15.0,
            )
            model_used = primary_model
        except Exception as primary_exc:
            if "429" in str(primary_exc) or "rate_limit" in str(primary_exc).lower():
                logger.warning("Primary model rate limited, trying %s fallback", fallback_model)
                response = client.chat.completions.create(
                    model=fallback_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=600,
                    timeout=15.0,
                )
                model_used = fallback_model
            else:
                raise primary_exc

        raw = response.choices[0].message.content.strip()
        # Strip any markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        # Repair truncated JSON — if token limit cut off the closing brace, add it back
        if raw and not raw.endswith("}"):
            raw = raw.rstrip().rstrip(",") + "}"
        result = json.loads(raw)

        # Validate required keys
        for key in ("recommended_route", "carrier", "eta_change_hours", "justification"):
            if key not in result:
                raise ValueError(f"Missing key: {key}")

        result["reasoning_source"] = "groq_llm"
        result["model_used"] = model_used
        logger.info(
            "Groq route recommendation for %s (%s) via %s: %s via %s",
            shipment_id, temp_class, model_used, result["recommended_route"], result["carrier"]
        )
        return result

    except Exception as exc:
        logger.warning("Groq API call failed: %s — using fallback", exc)
        route, carrier, eta = fallback_routes.get(temp_class, fallback_routes["refrigerated"])
        return {
            "recommended_route": route,
            "carrier": carrier,
            "eta_change_hours": eta,
            "justification": f"LLM unavailable ({type(exc).__name__}): {temp_class} product routed via certified carrier fallback.",
            "reasoning_source": "deterministic_fallback",
        }


class RouteInput(BaseModel):
    shipment_id: str = Field(description="Shipment to reroute")
    container_id: str = Field(description="Container within the shipment")
    current_leg_id: str = Field(description="Current transport leg")
    reason: str = Field(description="Why rerouting is requested")
    product_id: Optional[str] = Field(
        default=None,
        description="Product ID (P01-P06) for temperature class routing",
    )
    preferred_mode: Optional[str] = Field(
        default=None,
        description="Preferred transport mode: air, road, or None for auto",
    )
    # Rich context injected by orchestrator via _enrich_tool_input
    risk_tier: Optional[str] = Field(default=None)
    hours_to_breach: Optional[float] = Field(default=None)
    delay_class: Optional[str] = Field(default=None)
    avg_temp_c: Optional[float] = Field(default=None)
    temp_slope_c_per_hr: Optional[float] = Field(default=None)
    transit_phase: Optional[str] = Field(default=None)
    det_rules_fired: Optional[list] = Field(default=None)
    facility: Optional[dict] = Field(default=None)


def _execute(
    shipment_id: str,
    container_id: str,
    current_leg_id: str,
    reason: str,
    product_id: Optional[str] = None,
    preferred_mode: Optional[str] = None,
    risk_tier: Optional[str] = None,
    hours_to_breach: Optional[float] = None,
    delay_class: Optional[str] = None,
    avg_temp_c: Optional[float] = None,
    temp_slope_c_per_hr: Optional[float] = None,
    transit_phase: Optional[str] = None,
    det_rules_fired: Optional[list] = None,
    facility: Optional[dict] = None,
) -> dict:

    # Load .env if present
    env_path = _BASE / ".env"
    if env_path.exists() and not os.environ.get("GROQ_API_KEY"):
        for line in env_path.read_text().splitlines():
            if line.startswith("GROQ_API_KEY="):
                os.environ["GROQ_API_KEY"] = line.split("=", 1)[1].strip()

    temp_class = _get_temp_class(product_id) if product_id else "refrigerated"
    product_info = _get_product_info(product_id) if product_id else {}

    # Fetch live weather at destination
    weather = _fetch_weather(facility or {})

    # Build risk context for LLM
    risk_context = {
        "risk_tier": risk_tier or "CRITICAL",
        "hours_to_breach": hours_to_breach,
        "delay_class": delay_class or "unknown",
        "avg_temp_c": avg_temp_c,
        "temp_slope_c_per_hr": temp_slope_c_per_hr,
        "transit_phase": transit_phase or "unknown",
        "det_rules_fired": det_rules_fired or [],
    }

    # Call Groq for reasoning
    route_result = _call_groq_for_route(
        shipment_id=shipment_id,
        product_id=product_id or "unknown",
        temp_class=temp_class,
        product_info=product_info,
        reason=reason,
        preferred_mode=preferred_mode,
        weather=weather,
        risk_context=risk_context,
    )

    return {
        # Original cascade-required keys — unchanged
        "tool": "route_agent",
        "status": "recommendation_generated",
        "shipment_id": shipment_id,
        "container_id": container_id,
        "original_leg": current_leg_id,
        "recommended_route": route_result["recommended_route"],
        "carrier": route_result["carrier"],
        "eta_change_hours": route_result["eta_change_hours"],
        "temp_class": temp_class,
        "reason": reason,
        "requires_approval": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # New enriched fields
        "justification": route_result.get("justification", ""),
        "reasoning_source": route_result.get("reasoning_source", "unknown"),
        "model_used": route_result.get("model_used"),
        "weather_at_destination": weather,
    }


route_tool = StructuredTool.from_function(
    func=_execute,
    name="route_agent",
    description=(
        "Recommend an alternative route for a pharmaceutical shipment. "
        "Fetches live weather at destination via Open-Meteo, then calls "
        "an LLM to reason about the optimal carrier and route based on "
        "product temperature class, current breach status, delay severity, "
        "and weather conditions. Returns route recommendation with "
        "natural language justification. Requires human approval."
    ),
    args_schema=RouteInput,
)
