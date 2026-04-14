"""
simulate_stream.py
Replays single_table.csv into window_features row by row.
Simulates a live sensor feed for integration testing.
"""

import time, pandas as pd
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

df = pd.read_csv("single_table.csv")

DELAY_SECONDS = 1.0   # adjust: 0.1 = fast burn, 5 = realistic

print(f"Streaming {len(df)} windows at {DELAY_SECONDS}s intervals...\n")

for _, row in df.iterrows():
    record = row.where(row.notna(), other=None).to_dict()
    sb.table("window_features").insert(record).execute()
    print(f"  → inserted {record['window_id']} | shipment {record['shipment_id']}"
          f" | risk_label={record['target_spoilage_risk_6h']}")
    time.sleep(DELAY_SECONDS)