# test_insert.py  — run once to verify
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])



sb.table("window_features").insert({
    "window_id":              "W_TEST_003",
    "leg_id":                 "L0001",
    "shipment_id":            "S001",
    "container_id":           "C100",
    "product_id":             "P01",
    "window_start":           "2026-04-01T08:00:00",
    "window_end":             "2026-04-01T08:30:00",
    "avg_temp_c":             8.9,      # above safe range — should trigger HIGH risk
    "max_temp_c":             9.2,
    "min_temp_c":             8.1,
    "temp_slope_c_per_hr":    1.8,
    "humidity_avg_pct":       67.0,
    "shock_count":            2,
    "door_open_count":        1,
    "minutes_outside_range":  15,
    "current_delay_min":      142.0,
    "battery_avg_pct":        71.0,
    "transit_phase":          "customs_clearance",
    "target_spoilage_risk_6h": 1,
}).execute()

print("Test row inserted.")