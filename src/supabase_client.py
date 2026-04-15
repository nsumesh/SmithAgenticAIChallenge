"""
Supabase client — single source of truth for all project data.

Tables:
  window_features   — telemetry windows (7k+ rows)
  product_profiles  — product temp ranges & characteristics (6 rows)
  product_costs     — financial data per product
  facilities        — primary + backup facility per product

Falls back to local CSV/JSON if Supabase is unavailable.
Requires SUPABASE_URL and SUPABASE_KEY in .env.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
load_dotenv(_BASE / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client_cache = None

# ── Connection ────────────────────────────────────────────────────────

def _get_client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        _client_cache = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase connected: %s", SUPABASE_URL[:50])
        return _client_cache
    except Exception as e:
        logger.error("Supabase init failed: %s", e)
        return None


def is_available() -> bool:
    return _get_client() is not None


# ── Window Features (telemetry) ───────────────────────────────────────

def fetch_window_features(limit: int = 10000) -> Optional[pd.DataFrame]:
    """Fetch from Supabase window_features table → DataFrame (paginated)."""
    client = _get_client()
    if client is None:
        return None
    try:
        all_rows = []
        page_size = 1000
        offset = 0
        while offset < limit:
            batch = min(page_size, limit - offset)
            resp = (
                client.table("window_features")
                .select("*")
                .range(offset, offset + batch - 1)
                .execute()
            )
            if not resp.data:
                break
            all_rows.extend(resp.data)
            if len(resp.data) < batch:
                break
            offset += batch

        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows)
        drop_cols = [c for c in ("id", "ingested_at") if c in df.columns]
        if drop_cols:
            df = df.drop(columns=drop_cols)
        for col in ("window_start", "window_end"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
                df[col] = df[col].dt.tz_localize(None)
        logger.info("Supabase window_features: %d rows", len(df))
        return df
    except Exception as e:
        logger.error("window_features fetch failed: %s", e)
        return None


def fetch_window_by_id(window_id: str) -> Optional[dict]:
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("window_features").select("*").eq("window_id", window_id).limit(1).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.error("window fetch failed: %s", e)
        return None


# ── Product Profiles ──────────────────────────────────────────────────

_profiles_cache: Optional[Dict[str, dict]] = None

def fetch_product_profiles() -> Optional[Dict[str, dict]]:
    """Fetch product_profiles → dict keyed by product_id (same shape as local JSON)."""
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache

    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("product_profiles").select("*").execute()
        if not resp.data:
            return None
        result = {}
        for row in resp.data:
            pid = row.pop("product_id", None)
            if pid:
                result[pid] = row
        _profiles_cache = result
        logger.info("Supabase product_profiles: %d products", len(result))
        return result
    except Exception as e:
        logger.error("product_profiles fetch failed: %s", e)
        return None


# ── Product Costs ─────────────────────────────────────────────────────

_costs_cache: Optional[Dict[str, dict]] = None

def fetch_product_costs() -> Optional[Dict[str, dict]]:
    """Fetch product_costs → dict keyed by product_id."""
    global _costs_cache
    if _costs_cache is not None:
        return _costs_cache

    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("product_costs").select("*").execute()
        if not resp.data:
            return None
        result = {}
        for row in resp.data:
            pid = row.get("product_id", "")
            if pid:
                result[pid] = row
        _costs_cache = result
        logger.info("Supabase product_costs: %d products", len(result))
        return result
    except Exception as e:
        logger.error("product_costs fetch failed: %s", e)
        return None


# ── Facilities ────────────────────────────────────────────────────────

_facilities_cache: Optional[Dict[str, dict]] = None

def fetch_facilities() -> Optional[Dict[str, dict]]:
    """Fetch facilities → dict keyed by product_id (same shape as local JSON)."""
    global _facilities_cache
    if _facilities_cache is not None:
        return _facilities_cache

    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("facilities").select("*").execute()
        if not resp.data:
            return None
        result: Dict[str, dict] = {}
        for row in resp.data:
            pid = row.get("product_id", "")
            if not pid:
                continue
            role = row.get("role", "primary")
            if role == "primary" or pid not in result:
                result[pid] = row
        _facilities_cache = result
        logger.info("Supabase facilities: %d products", len(result))
        return result
    except Exception as e:
        logger.error("facilities fetch failed: %s", e)
        return None


# ── Write-back ────────────────────────────────────────────────────────

def write_risk_score(record: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("risk_scores").insert(record).execute()
        return True
    except Exception as e:
        logger.warning("risk_scores write failed: %s", e)
        return False


# ── Helpers for modules that load from local JSON ─────────────────────

def load_profiles_with_fallback() -> Dict[str, dict]:
    """Try Supabase first, fall back to local data/product_profiles.json."""
    profiles = fetch_product_profiles()
    if profiles:
        return profiles
    path = _BASE / "data" / "product_profiles.json"
    with open(path) as f:
        return json.load(f)


def load_costs_with_fallback() -> Dict[str, dict]:
    """Try Supabase first, fall back to local data/product_costs.json."""
    costs = fetch_product_costs()
    if costs:
        return costs
    path = _BASE / "data" / "product_costs.json"
    with open(path) as f:
        return json.load(f)


def load_facilities_with_fallback() -> Dict[str, dict]:
    """Try Supabase first, fall back to local data/facilities.json."""
    facs = fetch_facilities()
    if facs:
        return facs
    path = _BASE / "data" / "facilities.json"
    with open(path) as f:
        return json.load(f)
