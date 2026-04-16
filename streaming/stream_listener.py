"""
Supabase Realtime listener — bridges Supabase INSERT events on the
window_features table to the local FastAPI backend.

Flow:
  1. Subscribes to Supabase Realtime on window_features INSERT
  2. Forwards each new row to POST /api/ingest (risk scoring)
  3. If scored tier >= MEDIUM, auto-triggers POST /api/orchestrator/run/{window_id}

Requires SUPABASE_URL, SUPABASE_KEY in environment (or .env).

Usage:
    python -m streaming.stream_listener

Author: Karthik (Gen_Data), enhanced by Rahul
"""
import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv
from supabase._async.client import AsyncClient, create_client

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BACKEND_BASE = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")
INGEST_URL = f"{BACKEND_BASE}/api/ingest"
ORCHESTRATE_URL = f"{BACKEND_BASE}/api/orchestrator/run"
AUTO_ORCHESTRATE = os.environ.get("STREAM_AUTO_ORCHESTRATE", "true").lower() in ("1", "true", "yes")

_TIERS_TO_ORCHESTRATE = {"MEDIUM", "HIGH", "CRITICAL"}
_http: httpx.AsyncClient | None = None
_stats = {"ingested": 0, "orchestrated": 0, "errors": 0}


async def _forward_and_orchestrate(record: dict):
    """Score the row via /api/ingest and optionally trigger orchestration."""
    if _http is None:
        logger.warning("HTTP client not initialised; dropping row")
        return

    window_id = record.get("window_id", "?")
    shipment_id = record.get("shipment_id", "?")

    try:
        resp = await _http.post(INGEST_URL, json=record)
        resp.raise_for_status()
        scored = resp.json()

        tier = scored.get("risk_tier", "LOW")
        score = scored.get("risk_score", 0)
        _stats["ingested"] += 1

        logger.info(
            "SCORED  %s | shipment=%s | tier=%s score=%.4f",
            window_id, shipment_id, tier, score,
        )

        if AUTO_ORCHESTRATE and tier in _TIERS_TO_ORCHESTRATE and window_id != "?":
            try:
                orch_resp = await _http.post(f"{ORCHESTRATE_URL}/{window_id}")
                orch_resp.raise_for_status()
                orch = orch_resp.json()
                _stats["orchestrated"] += 1
                logger.info(
                    "ORCH    %s | tier=%s | actions=%d | approval=%s",
                    window_id, tier,
                    len(orch.get("actions_taken", [])),
                    orch.get("awaiting_approval", False),
                )
            except Exception as e:
                logger.warning("Orchestration failed for %s: %s", window_id, e)

    except httpx.ConnectError:
        _stats["errors"] += 1
        logger.warning("Backend unreachable for %s — is the server running?", window_id)
    except Exception as e:
        _stats["errors"] += 1
        logger.warning("Ingest failed for %s: %s", window_id, e)


def on_new_window(payload: dict):
    """Supabase Realtime callback for INSERT on window_features."""
    record = (
        payload.get("data", {}).get("record")
        or payload.get("record")
        or {}
    )
    window_id = record.get("window_id", "?")
    shipment_id = record.get("shipment_id", "?")

    logger.info(
        "STREAM  %s | shipment=%s | avg_temp=%s C | delay=%s min",
        window_id, shipment_id,
        record.get("avg_temp_c"), record.get("current_delay_min"),
    )

    try:
        asyncio.get_running_loop().create_task(_forward_and_orchestrate(record))
    except Exception as e:
        logger.warning("Could not schedule forward for %s: %s", window_id, e)


async def main():
    global _http
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Set SUPABASE_URL and SUPABASE_KEY in environment or .env")
        return

    logger.info("Connecting to Supabase Realtime...")
    logger.info("Backend target: %s", BACKEND_BASE)
    logger.info("Auto-orchestrate: %s (tiers: %s)", AUTO_ORCHESTRATE, _TIERS_TO_ORCHESTRATE)

    sb: AsyncClient = await create_client(SUPABASE_URL, SUPABASE_KEY)
    _http = httpx.AsyncClient(timeout=30)

    channel = sb.channel("window-stream")
    channel.on_postgres_changes(
        event="INSERT",
        schema="public",
        table="window_features",
        callback=on_new_window,
    )

    await channel.subscribe()
    logger.info("Subscribed to window_features. Waiting for new rows...\n")

    try:
        while True:
            await asyncio.sleep(30)
            logger.info(
                "STATS  ingested=%d orchestrated=%d errors=%d",
                _stats["ingested"], _stats["orchestrated"], _stats["errors"],
            )
    finally:
        await _http.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Listener stopped.")
