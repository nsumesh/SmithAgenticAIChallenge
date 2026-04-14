# stream_listener.py  (async version)
import os, asyncio, httpx
from supabase._async.client import AsyncClient, create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
RISK_AGENT_URL = os.environ.get("RISK_AGENT_URL", "http://localhost:8001/ingest")


def on_new_window(payload: dict):
    record = payload.get("data", {}).get("record", {})
    window_id   = record.get("window_id")
    shipment_id = record.get("shipment_id")

    print(f"[STREAM] {window_id} | shipment {shipment_id} | "
          f"avg_temp={record.get('avg_temp_c')}°C | "
          f"delay={record.get('current_delay_min')}min | "
          f"spoilage_risk={record.get('target_spoilage_risk_6h')}")

    # Forward the entire row to Rahul's endpoint
    try:
        resp = httpx.post(RISK_AGENT_URL, json=record, timeout=10)
        resp.raise_for_status()
        print(f"[SENT]  Row forwarded to risk agent successfully")
    except Exception as e:
        print(f"[WARN]  Risk agent not reachable: {e}")
# def on_new_window(payload: dict):
#     print("[RAW PAYLOAD]", payload)

async def main():
    print("[LISTENER] Starting — connected to ai_cargo_coldchain")

    sb: AsyncClient = await create_client(SUPABASE_URL, SUPABASE_KEY)

    channel = sb.channel("window-stream")
    channel.on_postgres_changes(
        event="INSERT",
        schema="public",
        table="window_features",
        callback=on_new_window,
    )

    await channel.subscribe()
    print("[LISTENER] Subscribed to window_features. Waiting for rows...\n")

    # Keep alive forever
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[LISTENER] Stopped.")