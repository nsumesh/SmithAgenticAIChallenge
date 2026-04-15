"""
backfill_source_tables.py
=========================
Run ONCE to populate shipments, containers, shipment_legs, raw_telemetry
from the existing window_features rows already in Supabase.

Usage:
    python backfill_source_tables.py
"""

import os, random, math
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
random.seed(42)

# ── Reference data (must match what was used to generate the CSV) ──
ROUTES = {
    # mode → (lat_o, lon_o, lat_d, lon_d, ambient, customs_risk, icao)
    "New York→Chicago":       ("air",  40.71,-74.00, 41.88,-87.63,  8.0,0.10,"KJFK"),
    "Atlanta→Miami":          ("road", 33.75,-84.39, 25.76,-80.19, 26.0,0.15,"KATL"),
    "Dallas→Denver":          ("air",  32.77,-96.79, 39.74,-104.99, 5.0,0.10,"KDFW"),
    "Mumbai→Frankfurt":       ("air",  19.08, 72.88, 50.11,  8.68, 28.0,0.55,"VABB"),
    "Frankfurt→Chicago":      ("air",  50.11,  8.68, 41.88,-87.63,  6.0,0.30,"EDDF"),
    "Singapore→London":       ("air",   1.36,103.99, 51.51, -0.13, 30.0,0.25,"WSSS"),
    "Nairobi→Amsterdam":      ("air",  -1.29, 36.82, 52.37,  4.90, 22.0,0.60,"HKJK"),
    "São Paulo→New York":     ("air", -23.55,-46.63, 40.71,-74.00, 24.0,0.40,"SBGR"),
    "Delhi→Dubai":            ("air",  28.70, 77.10, 25.20, 55.27, 32.0,0.50,"VIDP"),
    "Dubai→Johannesburg":     ("air",  25.20, 55.27,-26.20, 28.04, 35.0,0.45,"OMDB"),
    "Shanghai→Los Angeles":   ("sea",  31.23,121.47, 34.05,-118.24,18.0,0.35,"ZSPD"),
    "Rotterdam→New York":     ("sea",  51.92,  4.47, 40.71,-74.00,  9.0,0.20,"EHRD"),
    "Boston→Toronto":         ("road", 42.36,-71.06, 43.65,-79.38,  4.0,0.20,"KBOS"),
    "Paris→Lagos":            ("air",  48.86,  2.35,  6.52,  3.38, 12.0,0.65,"LFPG"),
    "Geneva→Islamabad":       ("air",  46.20,  6.14, 33.72, 73.04, 10.0,0.70,"LSGG"),
}
ROUTE_KEYS = list(ROUTES.keys())

CARRIERS = {
    "air":  ["AirCarrierA","LufthansaCargo","UnitedCargo","DeltaAirCargo","QatarCargo"],
    "road": ["RoadCarrierB","DHL Ground","FedEx Freight","UPS Supply Chain"],
    "sea":  ["Maersk Reefer","CMA CGM Cold","MSC Temperature"],
}

CONTAINER_SPECS = {
    "C100": {"reefer":"Active Reefer","insulation":"High",  "battery_start":98,
             "certified":"2-8C",   "max_kg":500,"mfr":"ThermoGuard"},
    "C205": {"reefer":"Passive Box", "insulation":"Medium","battery_start":85,
             "certified":"2-25C",  "max_kg":350,"mfr":"ColdPak"},
    "C330": {"reefer":"Active Reefer","insulation":"High",  "battery_start":92,
             "certified":"2-8C",   "max_kg":500,"mfr":"ThermoGuard"},
    "C410": {"reefer":"Cryogenic",   "insulation":"Ultra", "battery_start":99,
             "certified":"-80C to -15C","max_kg":150,"mfr":"CryoSafe"},
    "C515": {"reefer":"Passive Box", "insulation":"Low",   "battery_start":72,
             "certified":"2-25C",  "max_kg":300,"mfr":"BasicPak"},
    "C620": {"reefer":"Active Reefer","insulation":"Medium","battery_start":88,
             "certified":"1-8C",   "max_kg":450,"mfr":"ThermoGuard"},
}

WEATHER_CONDITIONS = ["clear","cloudy","rain","storm","fog"]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def run():
    print("Fetching existing window_features from Supabase...")

    # Pull all existing windows
    all_windows = []
    page_size = 1000
    offset = 0
    while True:
        resp = sb.table("window_features")\
            .select("*")\
            .range(offset, offset + page_size - 1)\
            .execute()
        batch = resp.data
        if not batch:
            break
        all_windows.extend(batch)
        offset += page_size
        print(f"  fetched {len(all_windows)} rows so far...")

    print(f"Total window_features rows: {len(all_windows)}\n")

    # ── 1. CONTAINERS (static, insert once) ──────────────────────
    print("Writing containers...")
    container_rows = []
    for cid, spec in CONTAINER_SPECS.items():
        container_rows.append({
            "container_id":             cid,
            "reefer_type":              spec["reefer"],
            "insulation_type":          spec["insulation"],
            "battery_health_start_pct": spec["battery_start"],
            "certified_temp_range":     spec["certified"],
            "max_payload_kg":           spec["max_kg"],
            "manufacturer":             spec["mfr"],
            "certification_expiry":     "2027-12-31",
            "last_inspection_date":     "2026-01-15",
            "gps_enabled":              True,
            "shock_sensor_enabled":     True,
            "door_sensor_enabled":      True,
        })
    sb.table("containers").upsert(container_rows).execute()
    print(f"  [OK] containers — {len(container_rows)} rows\n")

    # ── Group windows by shipment and leg ─────────────────────────
    shipments_seen = {}   # shipment_id → first window row
    legs_seen      = {}   # leg_id → list of window rows

    for w in all_windows:
        sid = w["shipment_id"]
        lid = w["leg_id"]
        if sid not in shipments_seen:
            shipments_seen[sid] = w
        if lid not in legs_seen:
            legs_seen[lid] = []
        legs_seen[lid].append(w)

    # ── 2. SHIPMENTS ──────────────────────────────────────────────
    print(f"Writing {len(shipments_seen)} shipments...")
    shipment_rows = []
    for sid, w in shipments_seen.items():
        route_key = random.choice(ROUTE_KEYS)
        r = ROUTES[route_key]
        mode, lat_o, lon_o, lat_d, lon_d, ambient, customs_risk, icao = r

        dep_dt = datetime.fromisoformat(w["window_start"].replace("Z",""))
        eta_dt = dep_dt + timedelta(hours=random.uniform(4, 52))

        shipment_rows.append({
            "shipment_id":       sid,
            "origin":            route_key.split("→")[0].strip(),
            "destination":       route_key.split("→")[1].strip(),
            "origin_lat":        round(lat_o, 5),
            "origin_lon":        round(lon_o, 5),
            "dest_lat":          round(lat_d, 5),
            "dest_lon":          round(lon_d, 5),
            "transport_mode":    mode,
            "carrier":           random.choice(CARRIERS[mode]),
            "planned_departure": dep_dt.isoformat(),
            "actual_departure":  dep_dt.isoformat(),
            "planned_eta":       eta_dt.isoformat(),
            "status":            "delivered",
            "ambient_temp_c":    ambient,
            "weather_condition": random.choice(WEATHER_CONDITIONS),
            "flight_delay_prob": round(random.uniform(0.05, 0.4), 3),
            "origin_icao":       icao,
            "customs_risk_score": customs_risk,
        })

    for batch in chunk(shipment_rows, 200):
        sb.table("shipments").upsert(batch).execute()
    print(f"  [OK] shipments — {len(shipment_rows)} rows\n")

    # ── 3. SHIPMENT_LEGS ──────────────────────────────────────────
    print(f"Writing {len(legs_seen)} shipment_legs...")
    leg_rows = []
    for lid, windows in legs_seen.items():
        w0   = windows[0]
        wlst = windows[-1]
        sid  = w0["shipment_id"]
        cid  = w0["container_id"]
        pid  = w0["product_id"]
        phase = w0["transit_phase"]

        # Find the shipment row to get mode/route
        s_row = shipments_seen.get(sid, {})
        origin = s_row.get("origin","") if isinstance(s_row, dict) else ""
        # Get mode from shipments_seen route
        route_key = random.choice(ROUTE_KEYS)
        mode = ROUTES[route_key][0]

        dep_dt = datetime.fromisoformat(w0["window_start"].replace("Z",""))
        eta_dt = datetime.fromisoformat(wlst["window_end"].replace("Z",""))
        max_delay = max(ww["current_delay_min"] for ww in windows)
        any_risk  = any(ww["target_spoilage_risk_6h"]==1 for ww in windows)

        leg_rows.append({
            "leg_id":            lid,
            "shipment_id":       sid,
            "container_id":      cid,
            "product_id":        pid,
            "carrier":           random.choice(CARRIERS[mode]),
            "route_segment":     route_key,
            "transport_mode":    mode,
            "transit_phase":     phase,
            "planned_departure": dep_dt.isoformat(),
            "planned_eta":       eta_dt.isoformat(),
            "actual_eta":        (eta_dt + timedelta(minutes=max_delay)).isoformat(),
            "current_delay_min": round(max_delay, 1),
            "leg_status":        "delivered",
            "anomaly_active":    any_risk,
        })

    for batch in chunk(leg_rows, 200):
        sb.table("shipment_legs").upsert(batch).execute()
    print(f"  [OK] shipment_legs — {len(leg_rows)} rows\n")

    # ── 4. RAW_TELEMETRY  (reconstruct ticks from window aggregates) ──
    print(f"Reconstructing raw_telemetry from window aggregates...")
    TICK_MIN = 5
    tele_rows = []
    tele_count = 0

    for lid, windows in legs_seen.items():
        for w_idx, w in enumerate(windows):
            cid = w["container_id"]
            pid = w["product_id"]
            spec = CONTAINER_SPECS.get(cid, CONTAINER_SPECS["C100"])

            window_start = datetime.fromisoformat(w["window_start"].replace("Z",""))
            avg_t = float(w["avg_temp_c"])
            max_t = float(w["max_temp_c"])
            min_t = float(w["min_temp_c"])
            slope = float(w["temp_slope_c_per_hr"])
            hum   = float(w["humidity_avg_pct"])
            batt  = float(w["battery_avg_pct"])

            # Reconstruct 6 ticks that are consistent with the window aggregates
            for tick_i in range(6):
                # Interpolate temp across window using slope
                t_offset_hr = (tick_i * TICK_MIN) / 60
                temp = avg_t + slope * (t_offset_hr - 0.125) + random.gauss(0, 0.05)
                temp = max(min_t, min(temp, max_t))

                shock = random.expovariate(20)
                if w["shock_count"] > 0 and tick_i == 2:
                    shock = random.uniform(0.6, 1.5)

                door = 1 if (w["door_open_count"] > 0 and tick_i == 3) else 0
                tick_time = window_start + timedelta(minutes=tick_i * TICK_MIN)

                tele_rows.append({
                    "telemetry_id": f"T-{lid}-{w_idx:04d}-{tick_i}",
                    "leg_id":       lid,
                    "timestamp":    tick_time.isoformat(),
                    "temperature_c": round(temp, 3),
                    "humidity_pct":  round(hum + random.gauss(0, 1), 2),
                    "shock_g":       round(min(shock, 5.0), 4),
                    "latitude":      round(random.uniform(-90, 90), 5),
                    "longitude":     round(random.uniform(-180, 180), 5),
                    "door_open":     door,
                    "battery_pct":   round(batt + random.gauss(0, 0.2), 2),
                })
                tele_count += 1

    print(f"  Writing {tele_count:,} telemetry rows in batches...")
    for i, batch in enumerate(chunk(tele_rows, 500)):
        sb.table("raw_telemetry").upsert(batch).execute()
        if (i+1) % 10 == 0:
            print(f"    ...{min((i+1)*500, tele_count):,}/{tele_count:,}")

    print(f"  [OK] raw_telemetry — {tele_count:,} rows\n")

    print("="*50)
    print("  Backfill complete.")
    print(f"  containers    : {len(container_rows)}")
    print(f"  shipments     : {len(shipment_rows)}")
    print(f"  shipment_legs : {len(leg_rows)}")
    print(f"  raw_telemetry : {tele_count:,}")
    print("="*50)


if __name__ == "__main__":
    run()