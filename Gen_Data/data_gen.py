"""
Pharmaceutical Cold Chain — Synthetic Data Generator v2
========================================================
Changes from v1 (per team feedback):
  1.  Single output table with exact schema requested
  2.  current_delay_min varies per window (cumulative live delay)
  3.  gps_risk_score dropped — raw signals only
  4.  anomaly_type removed (data leakage)
  5.  weather fields removed from feature table
  6.  Labels vary window-to-window within a leg (look-ahead based)
  7.  Battery: realistic monotonic drain, no random zeros
  8.  One product per container (enforced mapping)

Output: single_table.csv  (~600-1000 windows)

Public APIs used (free, no key):
  - Open-Meteo  : ambient temp per route (feeds physics, not a feature)
  - OpenSky     : flight delay probability per airport (feeds delay sim)
"""

import random, math, csv, json, os, time, urllib.request
from datetime import datetime, timedelta

random.seed(42)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
N_SHIPMENTS       = 140       # → expect 700-1000 windows
TICK_MIN          = 5         # sensor tick interval (minutes)
WINDOW_MIN        = 30        # rolling window size (minutes)
TICKS_PER_WINDOW  = WINDOW_MIN // TICK_MIN        # 6 ticks
HORIZON_TICKS     = int(6 * 60 / TICK_MIN)        # 72 ticks = 6 hours ahead
OUTPUT_DIR        = "/mnt/user-data/outputs"
OUTPUT_FILE       = os.path.join(OUTPUT_DIR, "test2.csv")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Exact output columns (as requested)
COLUMNS = [
    "window_id", "leg_id", "shipment_id", "container_id", "product_id",
    "window_start", "window_end",
    "avg_temp_c", "max_temp_c", "min_temp_c", "temp_slope_c_per_hr",
    "humidity_avg_pct", "shock_count", "door_open_count",
    "minutes_outside_range", "current_delay_min", "battery_avg_pct",
    "transit_phase", "target_spoilage_risk_6h",
]

# ─────────────────────────────────────────────
# WHO-INFORMED ROUTES
# (origin, dest, mode, lat_o, lon_o, lat_d, lon_d, ambient_c, customs_risk_0_1)
# ─────────────────────────────────────────────
ROUTES = [
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

CARRIERS = {
    "air":  ["AirCarrierA","LufthansaCargo","UnitedCargo","DeltaAirCargo","QatarCargo"],
    "road": ["RoadCarrierB","DHL Ground","FedEx Freight","UPS Supply Chain"],
    "sea":  ["Maersk Reefer","CMA CGM Cold","MSC Temperature"],
}

TRANSIT_PHASES = [
    "loading_zone", "air_handoff", "road_transit",
    "sea_transit", "customs_clearance", "cold_store_transfer", "last_mile",
]

# ─────────────────────────────────────────────
# PRODUCTS  (one product type per container — enforced below)
# ─────────────────────────────────────────────
PRODUCTS = {
    "P01": {"name": "Vaccine",           "t_lo":  2, "t_hi":  8, "sensitivity": "High"},
    "P02": {"name": "Biologic",          "t_lo":  2, "t_hi":  8, "sensitivity": "High"},
    "P03": {"name": "SpecialtyMedicine", "t_lo":  2, "t_hi": 25, "sensitivity": "Medium"},
    "P04": {"name": "mRNA Vaccine",      "t_lo":-20, "t_hi":-15, "sensitivity": "Critical"},
    "P05": {"name": "Blood Product",     "t_lo":  1, "t_hi":  6, "sensitivity": "High"},
    "P06": {"name": "Insulin",           "t_lo":  2, "t_hi":  8, "sensitivity": "Medium"},
}

# One product per container — fixed mapping
CONTAINER_PRODUCT = {
    "C100": "P01",   # Active Reefer High  → Vaccine
    "C205": "P03",   # Passive Box Medium  → Specialty Medicine
    "C330": "P02",   # Active Reefer High  → Biologic
    "C410": "P04",   # Cryogenic Ultra     → mRNA Vaccine
    "C515": "P06",   # Passive Box Low     → Insulin
    "C620": "P05",   # Active Reefer Med   → Blood Product
}

CONTAINER_SPECS = {
    "C100": {"reefer": "Active",  "insulation": "High",   "battery_start": 98},
    "C205": {"reefer": "Passive", "insulation": "Medium", "battery_start": 85},
    "C330": {"reefer": "Active",  "insulation": "High",   "battery_start": 92},
    "C410": {"reefer": "Cryo",   "insulation": "Ultra",  "battery_start": 99},
    "C515": {"reefer": "Passive", "insulation": "Low",    "battery_start": 72},
    "C620": {"reefer": "Active",  "insulation": "Medium", "battery_start": 88},
}

# ─────────────────────────────────────────────
# ANOMALY CATALOGUE
# (type, probability, temp_rise_c_per_hr, duration_hr_range, shock_multiplier)
# anomaly_type is NOT exposed as a feature — internal simulation only
# ─────────────────────────────────────────────
ANOMALIES = [
    ("none",             0.45,  0.00, (0,  0),    1.0),
    ("customs_hold",     0.12,  0.38, (2, 10),    1.0),
    ("tarmac_delay",     0.08,  0.22, (1,  3),    1.5),
    ("compressor_fault", 0.07,  0.70, (1,  5),    1.0),
    ("door_breach",      0.06,  0.95, (0.5,2),    1.0),
    ("port_congestion",  0.07,  0.28, (3, 12),    1.2),
    ("weather_divert",   0.05,  0.15, (2,  6),    3.5),
    ("ground_delay",     0.10,  0.20, (1,  4),    2.0),
]

def pick_anomaly():
    r, cumul = random.random(), 0.0
    for name, prob, rise, dur_range, shock_mult in ANOMALIES:
        cumul += prob
        if r < cumul:
            dur = random.uniform(*dur_range) if dur_range != (0, 0) else 0.0
            return {"type": name, "rise": rise, "dur_hr": dur, "shock_mult": shock_mult}
    return {"type": "none", "rise": 0, "dur_hr": 0, "shock_mult": 1.0}

# ─────────────────────────────────────────────
# PUBLIC API HELPERS  (Open-Meteo + OpenSky)
# ─────────────────────────────────────────────
_weather_cache, _delay_cache = {}, {}

def fetch_weather(lat, lon):
    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat:.2f}&longitude={lon:.2f}"
           f"&current=temperature_2m,windspeed_10m&forecast_days=1")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.loads(r.read())["current"]
        return float(d.get("temperature_2m", 15.0))
    except Exception:
        return 15.0   # fallback ambient

def get_ambient(lat, lon, key):
    if key not in _weather_cache:
        print(f"  [API] Open-Meteo: ({lat:.1f},{lon:.1f})")
        _weather_cache[key] = fetch_weather(lat, lon)
    return _weather_cache[key]

ICAO = {
    "New York":"KJFK","Chicago":"KORD","Atlanta":"KATL","Dallas":"KDFW",
    "Denver":"KDEN","Miami":"KMIA","Frankfurt":"EDDF","London":"EGLL",
    "Amsterdam":"EHAM","Singapore":"WSSS","Dubai":"OMDB","Mumbai":"VABB",
    "Delhi":"VIDP","Shanghai":"ZSPD","Los Angeles":"KLAX","São Paulo":"SBGR",
    "Nairobi":"HKJK","Geneva":"LSGG","Paris":"LFPG","Johannesburg":"FAOR",
    "Rotterdam":"EHRD","Boston":"KBOS","Toronto":"CYYZ","Islamabad":"OPNI",
    "Lagos":"DNMM",
}

def fetch_delay_prob(city):
    icao = ICAO.get(city, "KJFK")
    now  = int(time.time())
    url  = (f"https://opensky-network.org/api/flights/arrival"
            f"?airport={icao}&begin={now-3600}&end={now}")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            flights = json.loads(r.read())
        if not flights:
            return 0.15
        delayed = sum(1 for f in flights
                      if f.get("lastSeen",0) - f.get("firstSeen",0) > 900)
        return round(min(delayed / max(len(flights),1), 1.0), 3)
    except Exception:
        return round(random.uniform(0.05, 0.35), 3)

def get_delay_prob(city, mode):
    if mode != "air":
        return 0.0
    if city not in _delay_cache:
        print(f"  [API] OpenSky delay: {city}")
        _delay_cache[city] = fetch_delay_prob(city)
    return _delay_cache[city]

# ─────────────────────────────────────────────
# PHYSICS SIMULATOR — returns tick-level records
# ─────────────────────────────────────────────
def simulate_ticks(leg_id, container_id, product_id, route, anomaly,
                   dep_dt, dur_hr, ambient_c):
    """
    Returns list of per-tick dicts.
    current_delay_min accumulates realistically over time.
    Battery drains monotonically from starting health.
    No anomaly_type in output — internal only.
    """
    spec  = CONTAINER_SPECS[container_id]
    prod  = PRODUCTS[product_id]
    t_lo, t_hi = prod["t_lo"], prod["t_hi"]
    t_mid = (t_lo + t_hi) / 2

    # Insulation governs how fast ambient bleeds in
    insul_factor = {"Ultra": 0.15, "High": 0.40, "Medium": 0.85, "Low": 1.60}[spec["insulation"]]
    active       = spec["reefer"] in ("Active", "Cryo")

    n_ticks  = max(2, int(dur_hr * 60 / TICK_MIN))
    # Anomaly occupies a contiguous block after a quiet start
    an_start = random.randint(int(n_ticks * 0.15), int(n_ticks * 0.55))
    an_end   = an_start + int(anomaly["dur_hr"] * 60 / TICK_MIN)

    temp    = t_mid + random.uniform(-0.3, 0.3)
    battery = float(spec["battery_start"])
    # Battery drains at rate dependent on container type and duration
    battery_drain_per_tick = (spec["battery_start"] * 0.25) / max(n_ticks, 1) \
                              if active else (spec["battery_start"] * 0.08) / max(n_ticks, 1)

    origin, dest, mode, lat_o, lon_o, lat_d, lon_d, _, _ = route

    # ── delay accumulator ──────────────────────────────────
    # Starts near 0; anomaly adds delay incrementally per tick
    base_delay      = random.randint(0, 8)           # small pre-existing delay
    delay_min       = float(base_delay)
    delay_per_tick_in_anomaly = (anomaly["dur_hr"] * 60) / max(
        int(anomaly["dur_hr"] * 60 / TICK_MIN), 1
    ) if anomaly["dur_hr"] > 0 else 0.0

    ticks = []
    for i in range(n_ticks):
        progress = i / max(n_ticks - 1, 1)
        lat = lat_o + (lat_d - lat_o) * progress + random.gauss(0, 0.002)
        lon = lon_o + (lon_d - lon_o) * progress + random.gauss(0, 0.002)

        # Battery: monotonic drain, floor at 5 (not 0 — dead battery = alarm, not normal)
        battery = max(5.0, battery - battery_drain_per_tick + random.uniform(-0.01, 0.01))

        # Temperature physics
        temp += random.gauss(0, 0.07)                             # Brownian noise
        # Ambient bleed (worse when battery low / passive container)
        batt_efficiency = max(0.1, (battery - 5) / (spec["battery_start"] - 5 + 1e-9))
        bleed = (ambient_c - temp) * 0.003 * insul_factor
        if active:
            bleed *= (1 - batt_efficiency * 0.75)                 # active fights bleed
        temp += bleed

        in_anomaly = an_start <= i <= an_end and anomaly["type"] != "none"
        if in_anomaly:
            temp     += anomaly["rise"] * (TICK_MIN / 60)
            delay_min = min(delay_min + delay_per_tick_in_anomaly, 600)   # cap 10 hrs
        else:
            # Slight recovery post-anomaly
            if i > an_end:
                temp += (t_mid - temp) * 0.06

        # Small random noise on delay (traffic, etc.)
        delay_min = max(0, delay_min + random.gauss(0, 0.3))

        # Shock: log-normal; amplified by anomaly shock_mult
        shock = min(random.expovariate(18) * anomaly["shock_mult"] if in_anomaly
                    else random.expovariate(20), 5.0)

        door_open = 1 if (anomaly["type"] == "door_breach" and in_anomaly
                          and random.random() < 0.75) else 0

        humidity = max(10.0, min(98.0, random.gauss(
            55 + max(0, temp - t_hi) * 2.0, 3.0
        )))

        ticks.append({
            "leg_id":       leg_id,
            "timestamp":    dep_dt + timedelta(minutes=i * TICK_MIN),
            "temp":         round(temp, 3),
            "humidity":     round(humidity, 2),
            "shock_g":      round(shock, 4),
            "door_open":    door_open,
            "battery":      round(battery, 2),
            "delay_min":    round(delay_min, 1),   # live, varies per tick
            "t_lo":         t_lo,
            "t_hi":         t_hi,
        })

    return ticks


# ─────────────────────────────────────────────
# WINDOW AGGREGATION
# ─────────────────────────────────────────────
def aggregate_window(w_ticks, future_ticks, window_id, leg_id,
                     shipment_id, container_id, product_id, phase):
    """
    Aggregates one 30-min window into a single ML row.
    target_spoilage_risk_6h = 1 if future 6 hrs contain any temp excursion.
    """
    if not w_ticks:
        return None

    temps    = [t["temp"] for t in w_ticks]
    hums     = [t["humidity"] for t in w_ticks]
    shocks   = [t["shock_g"] for t in w_ticks]
    batts    = [t["battery"] for t in w_ticks]
    delays   = [t["delay_min"] for t in w_ticks]
    doors    = [t["door_open"] for t in w_ticks]
    t_lo, t_hi = w_ticks[0]["t_lo"], w_ticks[0]["t_hi"]

    n = len(temps)
    avg_t = sum(temps) / n

    # Linear slope via least squares
    if n > 1:
        xm = (n - 1) / 2
        num = sum((i - xm) * (temps[i] - avg_t) for i in range(n))
        den = sum((i - xm) ** 2 for i in range(n)) or 1e-9
        slope = round(num / den * (60 / TICK_MIN), 4)
    else:
        slope = 0.0

    minutes_outside = sum(TICK_MIN for t in temps if t < t_lo or t > t_hi)
    shock_count     = sum(1 for g in shocks if g > 0.5)

    # current_delay_min = last tick in window (most recent live reading)
    current_delay_min = round(delays[-1], 1)

    # TARGET: any excursion in the NEXT 6 hours?
    future_temps   = [ft["temp"] for ft in future_ticks]
    future_excursion = any(t < t_lo or t > t_hi for t in future_temps)
    current_excursion = any(t < t_lo or t > t_hi for t in temps)
    spoilage_risk  = int(current_excursion or future_excursion)

    return {
        "window_id":              window_id,
        "leg_id":                 leg_id,
        "shipment_id":            shipment_id,
        "container_id":           container_id,
        "product_id":             product_id,
        "window_start":           w_ticks[0]["timestamp"].strftime("%Y-%m-%d %H:%M"),
        "window_end":             w_ticks[-1]["timestamp"].strftime("%Y-%m-%d %H:%M"),
        "avg_temp_c":             round(avg_t, 3),
        "max_temp_c":             round(max(temps), 3),
        "min_temp_c":             round(min(temps), 3),
        "temp_slope_c_per_hr":    slope,
        "humidity_avg_pct":       round(sum(hums) / n, 2),
        "shock_count":            shock_count,
        "door_open_count":        sum(doors),
        "minutes_outside_range":  minutes_outside,
        "current_delay_min":      current_delay_min,
        "battery_avg_pct":        round(sum(batts) / n, 2),
        "transit_phase":          phase,
        "target_spoilage_risk_6h": spoilage_risk,
    }


# ─────────────────────────────────────────────
# MAIN GENERATION LOOP
# ─────────────────────────────────────────────
def generate():
    print(f"\n{'='*56}")
    print("  Cold Chain Data Generator v2")
    print(f"  {N_SHIPMENTS} shipments | window={WINDOW_MIN}min | horizon=6h")
    print(f"{'='*56}\n")

    rows        = []
    window_ctr  = 1
    leg_ctr     = 1
    base_dt     = datetime(2026, 4, 1, 8, 0)
    container_ids = list(CONTAINER_PRODUCT.keys())

    for s_idx in range(N_SHIPMENTS):
        s_id   = f"S{s_idx+1:03d}"
        route  = random.choice(ROUTES)
        origin, dest, mode = route[0], route[1], route[2]
        route_key = f"{origin}-{dest}"

        ambient = get_ambient(route[3], route[4], route_key)
        del_prob = get_delay_prob(origin, mode)

        dep_dt = base_dt + timedelta(hours=random.uniform(0, 72),
                                     minutes=random.randint(0, 59))

        # 1–3 legs per shipment; sea = 1 leg only
        n_legs = 1 if mode == "sea" else random.randint(1, 3)
        leg_start = dep_dt

        for l_idx in range(n_legs):
            leg_id      = f"L{leg_ctr:04d}"
            leg_ctr    += 1

            # One container → one product (enforced mapping)
            container_id = random.choice(container_ids)
            product_id   = CONTAINER_PRODUCT[container_id]

            if mode == "air":
                dur_hr = random.uniform(4, 14)
            elif mode == "road":
                dur_hr = random.uniform(2, 20)
            else:
                dur_hr = random.uniform(72, 240)
            dur_hr /= n_legs

            anomaly = pick_anomaly()

            # Randomise which transit phase this leg is in
            if l_idx == 0:
                phase = random.choice(["loading_zone", "air_handoff", "customs_clearance"])
            elif l_idx == n_legs - 1:
                phase = random.choice(["cold_store_transfer", "last_mile"])
            else:
                phase = random.choice(["road_transit", "sea_transit", "air_handoff"])

            ticks = simulate_ticks(
                leg_id, container_id, product_id, route,
                anomaly, leg_start, dur_hr, ambient
            )

            # Slide 30-min windows over the tick array
            for w in range(0, len(ticks) - TICKS_PER_WINDOW + 1, TICKS_PER_WINDOW):
                w_ticks = ticks[w : w + TICKS_PER_WINDOW]
                f_ticks = ticks[w + TICKS_PER_WINDOW :
                                w + TICKS_PER_WINDOW + HORIZON_TICKS]

                wid = f"W{window_ctr:05d}"
                window_ctr += 1

                row = aggregate_window(
                    w_ticks, f_ticks, wid, leg_id, s_id,
                    container_id, product_id, phase
                )
                if row:
                    rows.append(row)

            leg_start = leg_start + timedelta(hours=dur_hr)

        if (s_idx + 1) % 30 == 0:
            print(f"  Shipments done: {s_idx+1}/{N_SHIPMENTS}  |  "
                  f"Windows so far: {window_ctr-1:,}")

    return rows


# ─────────────────────────────────────────────
# STATS PRINTER
# ─────────────────────────────────────────────
def print_stats(rows):
    total   = len(rows)
    pos     = sum(1 for r in rows if r["target_spoilage_risk_6h"] == 1)
    neg     = total - pos

    delays  = [r["current_delay_min"] for r in rows]
    batts   = [r["battery_avg_pct"] for r in rows]
    excurs  = [r["minutes_outside_range"] for r in rows]

    phase_counts: dict = {}
    prod_counts:  dict = {}
    for r in rows:
        phase_counts[r["transit_phase"]] = phase_counts.get(r["transit_phase"], 0) + 1
        prod_counts[r["product_id"]]     = prod_counts.get(r["product_id"], 0) + 1

    print(f"\n{'='*56}")
    print("  DATASET SUMMARY")
    print(f"{'='*56}")
    print(f"  Total windows            : {total:>7,}")
    print(f"  Spoilage risk = 1 (pos)  : {pos:>7,}  ({100*pos//max(total,1)}%)")
    print(f"  Spoilage risk = 0 (neg)  : {neg:>7,}  ({100*neg//max(total,1)}%)")
    print(f"\n  current_delay_min")
    print(f"    min / mean / max       : {min(delays):.1f} / "
          f"{sum(delays)/max(len(delays),1):.1f} / {max(delays):.1f}")
    print(f"  battery_avg_pct")
    print(f"    min / mean / max       : {min(batts):.1f} / "
          f"{sum(batts)/max(len(batts),1):.1f} / {max(batts):.1f}")
    print(f"  minutes_outside_range")
    zero_excur = sum(1 for v in excurs if v == 0)
    print(f"    windows with 0 min     : {zero_excur:>7,}  ({100*zero_excur//max(total,1)}%)")

    print(f"\n  Transit phase distribution:")
    max_cnt = max(phase_counts.values(), default=1)
    for ph, cnt in sorted(phase_counts.items(), key=lambda x: -x[1]):
        bar = "█" * (cnt * 28 // max_cnt)
        print(f"    {ph:<25s} {cnt:>5,}  {bar}")

    print(f"\n  Product distribution (container→product fixed):")
    for pid, cnt in sorted(prod_counts.items()):
        print(f"    {pid}  {PRODUCTS[pid]['name']:<20s} {cnt:>5,} windows")

    print(f"{'='*56}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    rows = generate()

    print(f"\nWriting {len(rows):,} rows → {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print("Done.")

    print_stats(rows)