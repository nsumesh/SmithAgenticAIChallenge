"""
CSV replay → Supabase inserts — simulates a live sensor feed.

Reads data/single_table.csv and inserts rows to the Supabase
window_features table at configurable intervals.

Requires SUPABASE_URL, SUPABASE_KEY in environment (or .env).

Usage:
    python -m streaming.simulate_stream [--delay 1.0]

Author: Karthik (Gen_Data), integrated by Rahul
"""
import argparse
import os
import time
import logging

import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(_BASE, "data", "single_table.csv")


def main():
    parser = argparse.ArgumentParser(description="Replay CSV to Supabase")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to CSV file")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between inserts")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        logger.error("Set SUPABASE_URL and SUPABASE_KEY in environment or .env")
        return

    sb = create_client(url, key)
    df = pd.read_csv(args.csv)

    logger.info("Streaming %d windows at %.1fs intervals...", len(df), args.delay)

    for _, row in df.iterrows():
        record = row.where(row.notna(), other=None).to_dict()
        try:
            sb.table("telemetry").insert(record).execute()
            logger.info(
                "  → inserted %s | shipment %s | risk_label=%s",
                record.get("window_id"), record.get("shipment_id"),
                record.get("target_spoilage_risk_6h"),
            )
        except Exception as e:
            logger.warning("  ✗ insert failed: %s", e)
        time.sleep(args.delay)


if __name__ == "__main__":
    main()
