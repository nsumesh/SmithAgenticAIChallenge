"""
Supabase Realtime listener — bridges Supabase INSERT events on the
window_features table to the local FastAPI risk-scoring endpoint.

Requires SUPABASE_URL, SUPABASE_KEY in environment (or .env).

Usage:
    python -m streaming.stream_listener

Author: Karthik (Gen_Data), integrated by Rahul
"""
import os
import asyncio
import logging

import httpx
from supabase._async.client import AsyncClient, create_client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
RISK_AGENT_URL = os.environ.get("RISK_AGENT_URL", "http://localhost:8000/api/ingest")


def on_new_window(payload: dict):
    record = payload.get("data", {}).get("record", {})
    window_id = record.get("window_id")
    shipment_id = record.get("shipment_id")

    logger.info(
        "STREAM  %s | shipment %s | avg_temp=%s°C | delay=%smin",
        window_id, shipment_id,
        record.get("avg_temp_c"), record.get("current_delay_min"),
    )

    try:
        resp = httpx.post(RISK_AGENT_URL, json=record, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "SCORED  %s → tier=%s score=%.4f",
            window_id, result.get("risk_tier"), result.get("risk_score", 0),
        )
    except Exception as e:
        logger.warning("Risk agent not reachable: %s", e)


async def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Set SUPABASE_URL and SUPABASE_KEY in environment or .env")
        return

    logger.info("Connecting to Supabase Realtime...")
    sb: AsyncClient = await create_client(SUPABASE_URL, SUPABASE_KEY)

    channel = sb.channel("window-stream")
    channel.on_postgres_changes(
        event="INSERT",
        schema="public",
        table="telemetry",
        callback=on_new_window,
    )

    await channel.subscribe()
    logger.info("Subscribed to telemetry table. Waiting for rows...")

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Listener stopped.")
