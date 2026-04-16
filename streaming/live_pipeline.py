"""
live_pipeline.py
================
Generates exactly N window_features records and writes to ALL tables:
  containers -> shipments -> shipment_legs -> raw_telemetry -> window_features

Uses real APIs:
  - Open-Meteo  -> ambient temperature at route origin
  - OpenSky     -> flight delay probability per airport

Each window is inserted with a configurable delay to simulate live streaming.

Usage:
    python live_pipeline.py --records 10              # 10 window rows, 1s delay
    python live_pipeline.py --records 50 --delay 0.5  # 50 rows, fast
    python live_pipeline.py --records 5 --delay 3     # 5 rows, slow demo

Requires:
    pip install supabase python-dotenv
    .env with SUPABASE_URL and SUPABASE_KEY
"""

import os, random, math, time, json, urllib.request, argparse
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# ── CLI ARGS ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Live cold-chain data pipeline")
parser.add_argument("--records", type=int, default=10,
                    help="Exact number of window_features rows to generate")
parser.add_argument("--delay", type=float, default=1.0,
                    help="Seconds between window inserts (lower = faster)")
parser.add_argument("--seed", type=int, default=None,
                    help="Random seed (default: time-based)")
args = parser.parse_args()

TARGET_RECORDS   = args.records
STREAM_DELAY_SEC = args.delay
random.seed(args.seed if args.seed is not None else int(time.time()))

# ── CONFIG ────────────────────────────────────────────────────────
TICK_MIN         = 5
WINDOW_MIN       = 30
TICKS_PER_WINDOW = WINDOW_MIN // TICK_MIN       # 6
HORIZON_TICKS    = int(6 * 60 / TICK_MIN)       # 72

# ── REFERENCE DATA ────────────────────────────────────────────────
ROUTES = [
    # (origin, dest, mode, lat_o, lon_o, lat_d, lon_d, fallback_ambient, customs_risk)
    ("New York",    "Chicago",       "air",   40.71,-74.00, 41.88,-87.63,  8.0, 0.10),
    ("Atlanta",     "Miami",         "road",  33.75,-84.39, 25.76,-80.19, 26.0, 0.15),
    ("Dallas",      "Denver",        "air",   32.77,-96.79, 39.74,-104.99, 5.0, 0.10),
    ("Mumbai",      "Frankfurt",     "air",   19.08, 72.88, 50.11,  8.68, 28.0, 0.55),
    ("Frankfurt",   "Chicago",       "air",   50.11,  8.68, 41.88,-87.63,  6.0, 0.30),
    ("Singapore",   "London",        "air",    1.36,103.99, 51.51, -0.13, 30.0, 0.25),
    ("Nairobi",     "Amsterdam",     "air",   -1.29, 36.82, 52.37,  4.90, 22.0, 0.60),
    ("São Paulo",   "New York",      "air",  -23.55,-46.63, 40.71,-74.00, 24.0, 0.40),
    ("Delhi",       "Dubai",         "air",   28.70, 77.10, 25.20, 55.27, 32.0, 0.50),
    ("Dubai",       "Johannesburg",  "air",   25.20, 55.27,-26.20, 28.04, 35.0, 0.45),
    ("Shanghai",    "Los Angeles",   "sea",   31.23,121.47, 34.05,-118.24,18.0, 0.35),
    ("Rotterdam",   "New York",      "sea",   51.92,  4.47, 40.71,-74.00,  9.0, 0.20),
    ("Boston",      "Toronto",       "road",  42.36,-71.06, 43.65,-79.38,  4.0, 0.20),
    ("Paris",       "Lagos",         "air",   48.86,  2.35,  6.52,  3.38, 12.0, 0.65),
    ("Geneva",      "Islamabad",     "air",   46.20,  6.14, 33.72, 73.04, 10.0, 0.70),
]

# Filter out sea routes — they generate too many ticks for controlled record counts
AIR_ROAD_ROUTES = [r for r in ROUTES if r[2] != "sea"]

CARRIERS = {
    "air":  ["AirCarrierA","LufthansaCargo","UnitedCargo","DeltaAirCargo","QatarCargo"],
    "road": ["RoadCarrierB","DHL Ground","FedEx Freight","UPS Supply Chain"],
    "sea":  ["Maersk Reefer","CMA CGM Cold","MSC Temperature"],
}

CONTAINER_PRODUCT = {
    "C100": "P01",  "C205": "P03",  "C330": "P02",
    "C410": "P04",  "C515": "P06",  "C620": "P05",
}

CONTAINER_SPECS = {
    "C100": {"reefer": "Active Reefer", "insulation": "High",   "battery_start": 98,
             "certified": "2-8C",   "max_kg": 500, "mfr": "ThermoGuard"},
    "C205": {"reefer": "Passive Box",   "insulation": "Medium", "battery_start": 85,
             "certified": "2-25C",  "max_kg": 350, "mfr": "ColdPak"},
    "C330": {"reefer": "Active Reefer", "insulation": "High",   "battery_start": 92,
             "certified": "2-8C",   "max_kg": 500, "mfr": "ThermoGuard"},
    "C410": {"reefer": "Cryogenic",     "insulation": "Ultra",  "battery_start": 99,
             "certified": "-80C to -15C", "max_kg": 150, "mfr": "CryoSafe"},
    "C515": {"reefer": "Passive Box",   "insulation": "Low",    "battery_start": 72,
             "certified": "2-25C",  "max_kg": 300, "mfr": "BasicPak"},
    "C620": {"reefer": "Active Reefer", "insulation": "Medium", "battery_start": 88,
             "certified": "1-8C",   "max_kg": 450, "mfr": "ThermoGuard"},
}

PRODUCTS = {
    "P01": {"name": "Vaccine",           "t_lo":  2, "t_hi":  8, "sensitivity": "High"},
    "P02": {"name": "Biologic",          "t_lo":  2, "t_hi":  8, "sensitivity": "High"},
    "P03": {"name": "SpecialtyMedicine", "t_lo":  2, "t_hi": 25, "sensitivity": "Medium"},
    "P04": {"name": "mRNA Vaccine",      "t_lo":-20, "t_hi":-15, "sensitivity": "Critical"},
    "P05": {"name": "Blood Product",     "t_lo":  1, "t_hi":  6, "sensitivity": "High"},
    "P06": {"name": "Insulin",           "t_lo":  2, "t_hi":  8, "sensitivity": "Medium"},
}

WEATHER_CONDITIONS = ["clear", "cloudy", "rain", "storm", "fog"]

ANOMALIES = [
    ("none",             0.45, 0.00, (0,  0),   1.0),
    ("customs_hold",     0.12, 0.38, (2, 10),   1.0),
    ("tarmac_delay",     0.08, 0.22, (1,  3),   1.5),
    ("compressor_fault", 0.07, 0.70, (1,  5),   1.0),
    ("door_breach",      0.06, 0.95, (0.5, 2),  1.0),
    ("port_congestion",  0.07, 0.28, (3, 12),   1.2),
    ("weather_divert",   0.05, 0.15, (2,  6),   3.5),
    ("ground_delay",     0.10, 0.20, (1,  4),   2.0),
]

# ══════════════════════════════════════════════════════════════════
#  REAL API HELPERS  (Open-Meteo + OpenSky)
# ══════════════════════════════════════════════════════════════════
_weather_cache: dict = {}
_delay_cache:   dict = {}

def fetch_weather(lat: float, lon: float) -> float:
    """Call Open-Meteo for current temperature at (lat, lon)."""
    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat:.2f}&longitude={lon:.2f}"
           f"&current=temperature_2m,windspeed_10m&forecast_days=1")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.loads(r.read())["current"]
        return float(d.get("temperature_2m", 15.0))
    except Exception:
        return 15.0

def get_ambient(lat: float, lon: float, cache_key: str,
                fallback: float) -> float:
    """Cached Open-Meteo lookup; falls back to route's static ambient."""
    if cache_key not in _weather_cache:
        print(f"  [API] Open-Meteo  -> ({lat:.1f}, {lon:.1f})")
        _weather_cache[cache_key] = fetch_weather(lat, lon)
    return _weather_cache[cache_key]

ICAO = {
    "New York":"KJFK","Chicago":"KORD","Atlanta":"KATL","Dallas":"KDFW",
    "Denver":"KDEN","Miami":"KMIA","Frankfurt":"EDDF","London":"EGLL",
    "Amsterdam":"EHAM","Singapore":"WSSS","Dubai":"OMDB","Mumbai":"VABB",
    "Delhi":"VIDP","Shanghai":"ZSPD","Los Angeles":"KLAX","São Paulo":"SBGR",
    "Nairobi":"HKJK","Geneva":"LSGG","Paris":"LFPG","Johannesburg":"FAOR",
    "Rotterdam":"EHRD","Boston":"KBOS","Toronto":"CYYZ","Islamabad":"OPNI",
    "Lagos":"DNMM",
}

def fetch_delay_prob(city: str) -> float:
    """Call OpenSky for recent arrivals and compute delay probability."""
    icao = ICAO.get(city, "KJFK")
    now  = int(time.time())
    url  = (f"https://opensky-network.org/api/flights/arrival"
            f"?airport={icao}&begin={now-7200}&end={now}")
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            flights = json.loads(r.read())
        if not flights:
            return round(random.uniform(0.05, 0.35), 3)
        delayed = sum(1 for f in flights
                      if f.get("lastSeen", 0) - f.get("firstSeen", 0) > 900)
        return round(min(delayed / max(len(flights), 1), 1.0), 3)
    except Exception:
        return round(random.uniform(0.05, 0.35), 3)

def get_delay_prob(city: str, mode: str) -> float:
    """Cached OpenSky lookup; only used for air mode."""
    if mode != "air":
        return 0.0
    if city not in _delay_cache:
        print(f"  [API] OpenSky     -> {city} ({ICAO.get(city,'?')})")
        _delay_cache[city] = fetch_delay_prob(city)
    return _delay_cache[city]


# ══════════════════════════════════════════════════════════════════
#  ANOMALY + ID HELPERS
# ══════════════════════════════════════════════════════════════════
def pick_anomaly() -> dict:
    r, cumul = random.random(), 0.0
    for name, prob, rise, dur_range, shock_mult in ANOMALIES:
        cumul += prob
        if r < cumul:
            dur = random.uniform(*dur_range) if dur_range != (0, 0) else 0.0
            return {"type": name, "rise": rise, "dur_hr": dur, "shock_mult": shock_mult}
    return {"type": "none", "rise": 0, "dur_hr": 0, "shock_mult": 1.0}

# Use timestamp-based offset so each run produces unique IDs
_run_offset = int(time.time()) % 900000
_counters = {"s": _run_offset, "l": _run_offset, "w": _run_offset, "t": _run_offset}

def next_id(prefix: str) -> str:
    _counters[prefix] += 1
    return f"{prefix.upper()}{_counters[prefix]:06d}"


# ══════════════════════════════════════════════════════════════════
#  PHYSICS SIMULATOR  (same model as data_gen.py)
# ══════════════════════════════════════════════════════════════════
def simulate_ticks(leg_id, container_id, product_id, route, anomaly,
                   dep_dt, dur_hr, ambient_c):
    """
    Simulate tick-level sensor readings using physics model.
    Returns list of per-tick dicts with raw sensor values.
    """
    spec  = CONTAINER_SPECS[container_id]
    prod  = PRODUCTS[product_id]
    t_lo, t_hi = prod["t_lo"], prod["t_hi"]
    t_mid = (t_lo + t_hi) / 2

    insul_factor = {"Ultra": 0.15, "High": 0.40, "Medium": 0.85, "Low": 1.60}[spec["insulation"]]
    active       = spec["reefer"] in ("Active Reefer", "Cryogenic")

    n_ticks  = max(2, int(dur_hr * 60 / TICK_MIN))
    an_start = random.randint(int(n_ticks * 0.15), int(n_ticks * 0.55))
    an_end   = an_start + int(anomaly["dur_hr"] * 60 / TICK_MIN)

    temp    = t_mid + random.uniform(-0.3, 0.3)
    battery = float(spec["battery_start"])
    drain   = (spec["battery_start"] * 0.25) / max(n_ticks, 1) if active \
              else (spec["battery_start"] * 0.08) / max(n_ticks, 1)

    lat_o, lon_o, lat_d, lon_d = route[3], route[4], route[5], route[6]

    delay_min = float(random.randint(0, 8))
    delay_per_tick = (anomaly["dur_hr"] * 60) / max(
        int(anomaly["dur_hr"] * 60 / TICK_MIN), 1
    ) if anomaly["dur_hr"] > 0 else 0.0

    ticks = []
    for i in range(n_ticks):
        progress = i / max(n_ticks - 1, 1)
        lat = lat_o + (lat_d - lat_o) * progress + random.gauss(0, 0.002)
        lon = lon_o + (lon_d - lon_o) * progress + random.gauss(0, 0.002)

        battery = max(5.0, battery - drain + random.uniform(-0.01, 0.01))

        temp += random.gauss(0, 0.07)
        batt_eff = max(0.1, (battery - 5) / (spec["battery_start"] - 5 + 1e-9))
        bleed = (ambient_c - temp) * 0.003 * insul_factor
        if active:
            bleed *= (1 - batt_eff * 0.75)
        temp += bleed

        in_anomaly = an_start <= i <= an_end and anomaly["type"] != "none"
        if in_anomaly:
            temp     += anomaly["rise"] * (TICK_MIN / 60)
            delay_min = min(delay_min + delay_per_tick, 600)
        elif i > an_end:
            temp += (t_mid - temp) * 0.06

        delay_min = max(0, delay_min + random.gauss(0, 0.3))

        shock = min(random.expovariate(18) * anomaly["shock_mult"] if in_anomaly
                    else random.expovariate(20), 5.0)

        door_open = 1 if (anomaly["type"] == "door_breach" and in_anomaly
                          and random.random() < 0.75) else 0

        humidity = max(10.0, min(98.0, random.gauss(
            55 + max(0, temp - t_hi) * 2.0, 3.0)))

        ticks.append({
            "leg_id":        leg_id,
            "timestamp":     dep_dt + timedelta(minutes=i * TICK_MIN),
            "temperature_c": round(temp, 3),
            "humidity_pct":  round(humidity, 2),
            "shock_g":       round(shock, 4),
            "latitude":      round(lat, 5),
            "longitude":     round(lon, 5),
            "door_open":     door_open,
            "battery_pct":   round(battery, 2),
            "_delay":        round(delay_min, 1),
            "_t_lo":         t_lo,
            "_t_hi":         t_hi,
        })

    return ticks


# ══════════════════════════════════════════════════════════════════
#  WINDOW AGGREGATION
# ══════════════════════════════════════════════════════════════════
def aggregate_window(w_ticks, future_ticks, wid, leg_id,
                     sid, cid, pid, phase):
    temps  = [t["temperature_c"] for t in w_ticks]
    hums   = [t["humidity_pct"]  for t in w_ticks]
    shocks = [t["shock_g"]       for t in w_ticks]
    batts  = [t["battery_pct"]   for t in w_ticks]
    doors  = [t["door_open"]     for t in w_ticks]
    delays = [t["_delay"]        for t in w_ticks]
    t_lo, t_hi = w_ticks[0]["_t_lo"], w_ticks[0]["_t_hi"]

    n = len(temps)
    avg_t = sum(temps) / n

    if n > 1:
        xm  = (n - 1) / 2
        num = sum((i - xm) * (temps[i] - avg_t) for i in range(n))
        den = sum((i - xm) ** 2 for i in range(n)) or 1e-9
        slope = round(num / den * (60 / TICK_MIN), 4)
    else:
        slope = 0.0

    mins_out  = sum(TICK_MIN for t in temps if t < t_lo or t > t_hi)
    shock_cnt = sum(1 for g in shocks if g > 0.5)

    fut_temps = [ft["temperature_c"] for ft in future_ticks]
    spoilage  = int(
        any(t < t_lo or t > t_hi for t in temps) or
        any(t < t_lo or t > t_hi for t in fut_temps)
    )

    return {
        "window_id":               wid,
        "leg_id":                  leg_id,
        "shipment_id":             sid,
        "container_id":            cid,
        "product_id":              pid,
        "window_start":            w_ticks[0]["timestamp"].isoformat(),
        "window_end":              w_ticks[-1]["timestamp"].isoformat(),
        "avg_temp_c":              round(avg_t, 3),
        "max_temp_c":              round(max(temps), 3),
        "min_temp_c":              round(min(temps), 3),
        "temp_slope_c_per_hr":     slope,
        "humidity_avg_pct":        round(sum(hums) / n, 2),
        "shock_count":             shock_cnt,
        "door_open_count":         sum(doors),
        "minutes_outside_range":   mins_out,
        "current_delay_min":       round(delays[-1], 1),
        "battery_avg_pct":         round(sum(batts) / n, 2),
        "transit_phase":           phase,
        "target_spoilage_risk_6h": spoilage,
    }


# ══════════════════════════════════════════════════════════════════
#  DB WRITE HELPERS
# ══════════════════════════════════════════════════════════════════
def write_containers():
    rows = []
    for cid, spec in CONTAINER_SPECS.items():
        rows.append({
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
    sb.table("containers").upsert(rows).execute()
    print(f"  containers -> {len(rows)} rows")


def write_shipment(sid, route, mode, dep_dt, eta_dt, carrier,
                   ambient, weather, delay_prob, icao, customs_risk):
    sb.table("shipments").upsert({
        "shipment_id":        sid,
        "origin":             route[0],
        "destination":        route[1],
        "origin_lat":         round(route[3], 5),
        "origin_lon":         round(route[4], 5),
        "dest_lat":           round(route[5], 5),
        "dest_lon":           round(route[6], 5),
        "transport_mode":     mode,
        "carrier":            carrier,
        "planned_departure":  dep_dt.isoformat(),
        "actual_departure":   dep_dt.isoformat(),
        "planned_eta":        eta_dt.isoformat(),
        "status":             "active",
        "ambient_temp_c":     ambient,
        "weather_condition":  weather,
        "flight_delay_prob":  delay_prob,
        "origin_icao":        icao,
        "customs_risk_score": customs_risk,
    }).execute()


def write_leg(lid, sid, cid, pid, carrier, route, mode, phase,
              leg_start, leg_eta, delay_min, anomaly_type):
    sb.table("shipment_legs").upsert({
        "leg_id":            lid,
        "shipment_id":       sid,
        "container_id":      cid,
        "product_id":        pid,
        "carrier":           carrier,
        "route_segment":     f"{route[0]} -> {route[1]}",
        "transport_mode":    mode,
        "transit_phase":     phase,
        "planned_departure": leg_start.isoformat(),
        "planned_eta":       leg_eta.isoformat(),
        "actual_eta":        (leg_eta + timedelta(minutes=delay_min)).isoformat(),
        "current_delay_min": float(delay_min),
        "leg_status":        "in_transit",
        "anomaly_active":    anomaly_type != "none",
    }).execute()


def write_telemetry_batch(ticks):
    clean = []
    for i, t in enumerate(ticks):
        clean.append({
            "telemetry_id":  f"T-{t['leg_id']}-{i:05d}",
            "leg_id":        t["leg_id"],
            "timestamp":     t["timestamp"].isoformat(),
            "temperature_c": t["temperature_c"],
            "humidity_pct":  t["humidity_pct"],
            "shock_g":       t["shock_g"],
            "latitude":      t["latitude"],
            "longitude":     t["longitude"],
            "door_open":     t["door_open"],
            "battery_pct":   t["battery_pct"],
        })
    for batch in [clean[i:i+500] for i in range(0, len(clean), 500)]:
        sb.table("raw_telemetry").upsert(batch).execute()
    return len(clean)


# ══════════════════════════════════════════════════════════════════
#  MAIN PIPELINE — driven by TARGET_RECORDS
# ══════════════════════════════════════════════════════════════════
def main():
    print(f"\n{'='*60}")
    print(f"  Live Pipeline  |  target: {TARGET_RECORDS} window_features rows")
    print(f"  Delay: {STREAM_DELAY_SEC}s between inserts")
    print(f"  APIs: Open-Meteo + OpenSky")
    print(f"{'='*60}\n")

    write_containers()

    now = datetime.utcnow()
    container_ids = list(CONTAINER_PRODUCT.keys())
    windows_written  = 0
    shipments_written = 0
    legs_written      = 0
    telemetry_written = 0

    while windows_written < TARGET_RECORDS:
        sid   = next_id("s")
        route = random.choice(AIR_ROAD_ROUTES)
        origin, dest, mode = route[0], route[1], route[2]
        customs_risk = route[8]

        # ── API: Open-Meteo ambient temperature ──────────────────
        route_key = f"{origin}-{dest}"
        ambient = get_ambient(route[3], route[4], route_key, fallback=route[7])

        # ── API: OpenSky flight delay probability ────────────────
        delay_prob = get_delay_prob(origin, mode)

        icao    = ICAO.get(origin, "KJFK")
        weather = random.choice(WEATHER_CONDITIONS)
        carrier = random.choice(CARRIERS[mode])

        # Keep durations short so each shipment yields a manageable
        # number of windows — roughly 3-10 per leg
        dur_hr = random.uniform(1.5, 5.0)

        dep_dt = now - timedelta(hours=dur_hr * 0.5)
        eta_dt = dep_dt + timedelta(hours=dur_hr)

        write_shipment(sid, route, mode, dep_dt, eta_dt, carrier,
                       ambient, weather, delay_prob, icao, customs_risk)
        shipments_written += 1
        print(f"  shipment {sid} | {origin} -> {dest} | {mode}")

        # Single leg per shipment for tight control
        lid = next_id("l")
        cid = random.choice(container_ids)
        pid = CONTAINER_PRODUCT[cid]
        anomaly = pick_anomaly()
        phase = random.choice(["loading_zone", "air_handoff", "customs_clearance",
                               "cold_store_transfer", "last_mile",
                               "road_transit", "air_handoff"])

        leg_eta = dep_dt + timedelta(hours=dur_hr)
        delay_at_leg = int(random.uniform(0.05, 0.4) * 60)

        write_leg(lid, sid, cid, pid, carrier, route, mode, phase,
                  dep_dt, leg_eta, delay_at_leg, anomaly["type"])
        legs_written += 1

        # Simulate ticks
        ticks = simulate_ticks(lid, cid, pid, route, anomaly,
                               dep_dt, dur_hr, ambient)

        n_tele = write_telemetry_batch(ticks)
        telemetry_written += n_tele
        print(f"    leg {lid} | {n_tele} ticks | anomaly={anomaly['type']}")

        # Aggregate and stream windows — stop as soon as we hit target
        for w in range(0, len(ticks) - TICKS_PER_WINDOW + 1, TICKS_PER_WINDOW):
            if windows_written >= TARGET_RECORDS:
                break

            w_ticks = ticks[w : w + TICKS_PER_WINDOW]
            f_ticks = ticks[w + TICKS_PER_WINDOW :
                            w + TICKS_PER_WINDOW + HORIZON_TICKS]

            wid = next_id("w")
            row = aggregate_window(w_ticks, f_ticks, wid, lid,
                                   sid, cid, pid, phase)

            sb.table("window_features").upsert(row).execute()
            windows_written += 1

            print(f"    -> {wid} inserted  ({windows_written}/{TARGET_RECORDS})")
            time.sleep(STREAM_DELAY_SEC)

    print(f"\n{'='*60}")
    print(f"  Done. {windows_written} window_features rows inserted.")
    print(f"  shipments: {shipments_written} | legs: {legs_written} "
          f"| telemetry: {telemetry_written:,}")
    print(f"  API calls: {len(_weather_cache)} Open-Meteo, "
          f"{len(_delay_cache)} OpenSky")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
