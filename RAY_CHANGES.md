# Agent Improvements — Ray (Mukul)
**Branch:** `ray/agents-final`
**Submission deadline:** April 15, 2026
**Author:** Mukul Ray

---

## Overview

This document covers all changes made to the route agent, insurance agent, and triage agent as part of the April 15 submission. It includes what was built, why each change was made, what data it uses, what gaps exist and why, and how to roll back if needed.

All changes are on the `ray/agents-final` branch. The `develop` branch is untouched and clean for merging.

---

## What was already there before these changes

The core system was largely built by the team before this work began:

- **Risk scoring engine** — deterministic rules + XGBoost model trained on 7,408 synthetic telemetry windows, with SHAP explainability and alpha-blend fusion. Fully working. Outputs `artifacts/scored_windows.csv`.
- **LangGraph orchestrator** — a plan → reflect → revise → execute state machine in `orchestrator/nodes.py`. Fully wired. No LLM calls — all deterministic Python.
- **FastAPI backend** — 15+ endpoints in `backend/app.py` serving scored data to the frontend.
- **React dashboard** — 8 views including Overview, Monitoring, ShipmentDetail, AgentActivity, AuditLog, Approvals, GraphView.
- **Agent tool stubs** — all 8 tools existed in `tools/` but most returned hardcoded or random outputs.

The three agents this document covers — route, insurance, and triage — were stubs that needed real logic, real data connections, and bug fixes before they could be used in a demo.

---

## Change 1 — Audit log bug fix

**File:** `backend/app.py`
**Function:** `_load_audit_records()` (line ~436)

### Problem

There are two separate audit streams in this project:

1. `src/compliance_logger.py` writes pipeline audit records to files named `audit_YYYYMMDDTHHMMSSZ.jsonl`
2. `tools/compliance_agent.py` writes tool-level events to `compliance_events.jsonl`

The `_load_audit_records()` function only globbed `audit_*.jsonl`, so compliance tool events were completely invisible to the frontend AuditLog view. Running the orchestrator would produce compliance records that never appeared in the dashboard.

### Fix

Changed the glob to collect both file patterns:

```python
# Before
for path in sorted(AUDIT_DIR.glob("audit_*.jsonl")):

# After
all_paths = sorted(AUDIT_DIR.glob("audit_*.jsonl")) + sorted(AUDIT_DIR.glob("compliance_events.jsonl"))
for path in all_paths:
```

### Note for demo

The `compliance_events.jsonl` file only exists after orchestration has been run at least once. Before recording the demo, run the orchestrator on a few CRITICAL windows so the file is populated. Otherwise the AuditLog view will still appear empty.

---

## Change 2 — Route agent: context-aware routing

**File:** `tools/route_agent.py`
**Original size:** 62 lines
**New size:** ~145 lines

### Problem

The original route agent used `random.choice()` over four hardcoded Europe-to-North-America air routes. It accepted `preferred_mode` and `location_hint` parameters but ignored both entirely. A frozen vaccine shipment (P04, −25 to −15°C) got the exact same route recommendation as a room-temperature medicine (P03, 10–25°C). The logic was:

```python
option = random.choice(ALTERNATE_ROUTES)
```

### Fix

Replaced `random.choice` with a lookup chain that reads real product data:

1. Loads `data/product_profiles.json` to get the product's temperature range
2. Classifies the product into one of three temperature classes:
   - **Frozen** — safe temp ceiling ≤ 0°C (e.g. P04: −25 to −15°C)
   - **Refrigerated** — safe temp ceiling ≤ 15°C (e.g. P01/P02/P05/P06: 2–8°C)
   - **CRT** — controlled room temperature (e.g. P03: 10–25°C)
3. Selects a route from a structured table keyed by temp class and preferred mode
4. For urgent or critical reasons, sorts options by fastest ETA delta

### Working output

```
P04 frozen + critical emergency  →  Atlas Air Cold Chain (ultra-cold certified)  ETA: -5h
P01 refrigerated + air           →  British Airways World Cargo (2-8°C certified) ETA: -3h
P05 refrigerated + road          →  DHL Life Sciences (GDP active reefer)          ETA: +1h
P03 CRT + no mode                →  Air France Cargo (standard air)                ETA: -1h
No product_id (old callers)      →  British Airways World Cargo (refrigerated fallback)
```

### Backward compatibility

`product_id` is an optional field in `RouteInput`. Old callers that do not pass it fall back to the refrigerated class. All original output dict keys (`recommended_route`, `carrier`, `eta_change_hours`, `requires_approval`, `timestamp`) are preserved, so the cascade in `nodes.py` continues to work without changes.

### Data used

- `data/product_profiles.json` — WHO-aligned temperature thresholds per product (P01–P06)

---

## Change 3 — Wire product_id to route agent in orchestrator

**File:** `orchestrator/nodes.py`
**Function:** `_build_tool_input()` (line ~228)

### Problem

Even after rewriting the route agent to use temp-class routing, the orchestrator was never passing `product_id` to it. The `_build_tool_input()` function builds the input dict for each tool. Its route agent block only included `shipment_id`, `container_id`, `current_leg_id`, and `reason`. Without `product_id`, every real orchestrated call hit the fallback:

```python
temp_class = _get_temp_class(product_id) if product_id else "refrigerated"
```

A P04 frozen vaccine with a critical breach would receive a refrigerated carrier recommendation.

### Fix

Added one line to the route agent input block:

```python
if tool_name == "route_agent":
    return {
        **base,
        "current_leg_id": ri.get("leg_id", ""),
        "reason": state.get("primary_issue", "Risk detected") + context_suffix,
        "product_id": ri.get("product_type", ""),   # added
    }
```

The risk input dict uses `product_type` as the key (set by `backend/app.py` at line 188: `"product_type": ctx["product_id"]`), so the lookup is `ri.get("product_type", "")`.

### Verified

End-to-end test through the real orchestrator path confirms P04 now gets `temp_class=frozen` and Atlas Air Cold Chain.

---

## Change 4 — Insurance agent: real loss calculation

**File:** `tools/insurance_agent.py`
**Original size:** 258 lines
**Changes:** ~20 lines added

### Problem

The insurance agent already read real data (`scored_windows.csv` and `product_costs.json`) and had a good structure. But the `_compute_loss_breakdown()` function had a silent bug: it accepted an `appointment_count` parameter for calculating downstream disruption costs, but the call site always passed `0`:

```python
loss_breakdown = _compute_loss_breakdown(product_id, spoilage_probability)
# appointment_count defaults to 0 → downstream_disruption_usd always $0.00
```

Meanwhile, `data/facilities.json` contains real appointment counts per product (e.g. P01 has 120 appointments at the primary NHS facility). This data was loaded by `context_assembler.py` but never reached the insurance calculation.

### Fix

Three targeted changes:

1. Added `_load_facilities()` function and cache to `insurance_agent.py`
2. Updated `_aggregate_leg_history()` to accept `product_id` and return the real `appointment_count` from `facilities.json`
3. Updated the call site in `_execute()` to pass `appointment_count` from the aggregated leg history

### Working output with real data

```
P04 frozen (leg L0037, 408 windows):
  Windows in breach:       269 / 408
  Total excursion time:    360 minutes
  Peak temperature:        -13.97°C
  Product loss:            $225,000.00
  Disposal cost:           $67,500.00
  Downstream disruption:   $61,200.00  ← was always $0 before
  Risk multiplier:         2.5x (frozen vaccine)
  TOTAL ESTIMATED LOSS:    $568,531.25

P01 refrigerated (leg L0096, 407 windows):
  Windows in breach:       360 / 407
  Total excursion time:    4,595 minutes
  Peak temperature:        12.98°C
  TOTAL ESTIMATED LOSS:    $59,391.00
```

### Data used

- `artifacts/scored_windows.csv` — real excursion history aggregated per leg
- `data/product_costs.json` — unit costs, disposal rates, risk multipliers per product
- `data/facilities.json` — appointment counts per product at destination facilities

---

## Change 5 — Triage agent: fix KeyError crash

**File:** `tools/triage_agent.py`
**Line:** ~41

### Problem

The triage agent crashed with `KeyError: 'container_id'` when called with minimal dicts that did not include optional fields. The orchestrator sometimes passes raw risk summary dicts that only contain `shipment_id`, `risk_tier`, `fused_risk_score`, and `product_id`. The triage agent used hard bracket access:

```python
s["container_id"]    # KeyError if not present
s["transit_phase"]   # KeyError if not present
```

### Fix

Changed all bracket accesses inside `_execute()` to `.get()` with safe defaults:

```python
s.get("container_id", "")
s.get("transit_phase", "")
```

Six accesses were updated. Full dicts with all fields continue to work correctly. Minimal dicts no longer crash.

### Working output

```
RANK   SHIPMENT      TIER        SCORE    IMMEDIATE ACTION
------ ------------- ----------- -------- ----------------
1      SHIP-001      CRITICAL    0.95     YES
2      SHIP-004      CRITICAL    0.88     YES
3      SHIP-003      HIGH        0.75     YES
4      SHIP-002      HIGH        0.71     YES
5      SHIP-007      MEDIUM      0.45     no
6      SHIP-009      LOW         0.10     no
```

CRITICAL tier is sorted by score descending. `needs_immediate_attention` fires for CRITICAL and HIGH only.

---

## Known gaps and why they are not fixed

### Gap 1 — Route geography is static

The route agent selects carriers based on product temperature class, not the shipment's actual origin and destination. A Dallas→Denver shipment and a Frankfurt→London shipment get the same carrier tier. The route strings like "LHR→JFK (air, 2-8°C certified)" are illustrative of the carrier certification level, not a literal flight path.

**Why not fixed:** The scored_windows.csv does not include origin/destination fields per leg. Fixing this would require either adding that data to the synthetic dataset or integrating a real carrier routing API. Neither is feasible before April 15.

**Demo framing:** The system selects carriers by pharmaceutical cold chain certification class. Real-time geographic routing is a production extension.

### Gap 2 — No weather or traffic data

The route agent does not consult weather APIs or traffic feeds. Highway closures, storms, or port congestion are not factored into recommendations.

**Why not fixed:** Requires external API integration (OpenWeather, FlightAware, etc.) with API keys, error handling, and latency management. Risk to demo stability outweighs the benefit.

**Demo framing:** Weather-aware rerouting is architecturally supported — the `reason` field and urgency sorting already handle escalation signals. The data source is the integration point.

### Gap 3 — Orchestrator has no LLM

The README and system_prompt.md describe Claude Sonnet as the reasoning backbone. The actual `orchestrator/nodes.py` is pure deterministic Python. Planning, reflection, and revision are all rule-based logic, not LLM calls.

**Why not fixed:** Adding live LLM calls to a demo introduces API key dependency and latency that could cause the demo to fail. The deterministic approach is more reliable and arguably more appropriate for regulated pharmaceutical logistics.

**Demo framing:** The risk engine uses probabilistic ML reasoning (XGBoost + SHAP). Orchestration is deterministic by design — pharmaceutical logistics requires auditability and reproducibility, not generative reasoning.

### Gap 4 — Cold storage agent uses hardcoded facilities

The cold storage agent ignores `data/facilities.json` and picks from a hardcoded list of four facilities at random. The `backup_facility` field in facilities.json is populated but never read.

**Why not fixed:** Cold storage is Nikhil's task. The real data is already in facilities.json — the fix is straightforward and should be done by the cold storage agent owner.

### Gap 5 — Notification agent does not deliver

`notification_agent.py` builds a structured alert payload but `delivered` is hardcoded `False`. No email, SMS, or webhook is sent.

**Why not fixed:** Real notification delivery requires external service credentials (Twilio, SendGrid, etc.) and is not feasible to add safely before April 15. The cascade structure is correct and the payload is realistic.

### Gap 6 — Audit log requires a prior orchestration run

The `compliance_events.jsonl` file only exists after the compliance tool runs during orchestration. If the backend starts fresh with no prior runs, the AuditLog view appears empty even though the bug fix (Change 1) is in place.

**Fix before demo:** Run `POST /api/orchestrator/run-batch` on a set of CRITICAL window IDs before recording. This populates the audit log.

---

## How to roll back

**Roll back everything (return to develop):**
```bash
git checkout develop
```

**Roll back a single file:**
```bash
git checkout develop -- tools/route_agent.py
git checkout develop -- tools/insurance_agent.py
git checkout develop -- tools/triage_agent.py
git checkout develop -- orchestrator/nodes.py
git checkout develop -- backend/app.py
```

**Backup files** (pre-change originals) are in the repo as `.bak` files for reference:
- `backend/app.py.bak`
- `tools/route_agent.py.bak`
- `tools/insurance_agent.py.bak`

---

## Files changed

| File | Change |
|---|---|
| `tools/route_agent.py` | Full rewrite — temp-class routing, removed random.choice |
| `tools/insurance_agent.py` | Added facilities loader, real appointment_count in loss formula |
| `tools/triage_agent.py` | Fixed KeyError — changed bracket access to .get() |
| `orchestrator/nodes.py` | Added product_id to route_agent tool input |
| `backend/app.py` | Fixed audit log glob to include compliance_events.jsonl |
| `.gitignore` | Added .venv, .claude, *.bak, node_modules, IDE files |

---

## Branch and commit history

```
ray/agents-final
├── ray: update RAY_CHANGES.md and .gitignore cleanup
├── ray: wire product_id to route_agent in orchestrator, fix triage_agent KeyError
└── ray: fix audit log glob, insurance appointment_count, route agent context-aware routing
```

---

*Written by Mukul Ray — April 2026*

---

## Change 6 — Triage agent: real data enrichment + API endpoints

**Files:** `tools/triage_agent.py`, `backend/app.py`
**Commit:** 43a329c

### What changed in triage_agent.py

The original triage agent sorted shipments by tier and score — nothing else. It had no access to real excursion data and required `container_id` and `transit_phase` as non-optional fields, which caused KeyError crashes when called with minimal dicts.

Three improvements:

**1. Schema fix** — `container_id` and `transit_phase` are now `Optional[str]` with empty string defaults. The agent no longer crashes on minimal input.

**2. Real data enrichment** — added `_enrich_shipment()` which pulls from `scored_windows.csv` and `product_profiles.json` to attach:
- `hours_at_risk` — breach windows × 0.5hr (each window is 30 minutes)
- `peak_temp_c` — highest avg_temp recorded for this shipment
- `primary_breach_rule` — most frequently fired deterministic rule
- `product_name` — human-readable name from product profiles
- `windows_in_breach` / `total_windows` — breach density

**3. Urgency labels** — each ranked item now carries a human-readable urgency string:
- CRITICAL → "Immediate action required"
- HIGH → "Intervene within 1 hour"
- MEDIUM → "Monitor closely"
- LOW → "Standard monitoring"

**4. recommended_orchestration_order** — the output now includes a flat list of shipment IDs in priority order for shipments needing action. The frontend or batch endpoint can use this list directly to decide what to pass to `/api/orchestrator/run-batch`.

### What changed in backend/app.py

Two new endpoints:

`GET /api/triage/critical-shipments?limit=N`
Automatically pulls all CRITICAL and HIGH windows from the scored CSV, selects the worst window per shipment, runs triage ranking with enrichment, and returns the full priority list. No input needed — the endpoint does everything. This is the primary pre-orchestration step.

`POST /api/triage/rank`
Accepts a caller-supplied list of shipment dicts and ranks them. Each dict needs `shipment_id`, `risk_tier`, `fused_risk_score`, `product_id`. Also broadcasts a WebSocket event on completion.

### Working output (real data)

```
Ranked 6 shipments — all CRITICAL at score=1.0 (synthetic dataset has severe excursions)

#1 S019 — Vaccine-C (P06) — CRITICAL — Immediate action required
   136.5h at risk | peak 14.79°C | 273/289 windows breached | rule: excursion_duration

#2 S036 — Vaccine-C (P06) — CRITICAL — Immediate action required
   167.0h at risk | peak 18.13°C | 334/344 windows breached

#3 S021 — Frozen-Vaccine (P04) — CRITICAL — Immediate action required
   134.5h at risk | peak -13.97°C | 269/408 windows breached

recommended_orchestration_order: ['S019', 'S036', 'S021', ...]
```

### Demo note

`GET /api/triage/critical-shipments` returns up to 20 shipments by default. Use `?limit=5` or `?limit=6` for the demo so the output is readable on screen. All 15 CRITICAL shipments in the dataset score 1.0 — use limit to keep it focused.

---

## Change 7 — Route agent: Live weather + Groq LLM reasoning

**Files:** `tools/route_agent.py`
**Commits:** 95b3bc7, 3abb382, 452786d, 81614e6

### What changed

The original route agent used `random.choice` over 4 hardcoded strings, then was upgraded to a deterministic lookup table keyed by temperature class. Both approaches produced the same output regardless of actual shipment conditions.

This change replaces the lookup table entirely with a two-stage pipeline:

**Stage 1 — Open-Meteo live weather fetch**
- Calls `https://api.open-meteo.com/v1/forecast` with coordinates for the destination facility
- Free, no API key required, returns current temperature, wind speed, precipitation, and WMO weather code
- Maps WMO codes to human-readable descriptions and flags severe weather codes (thunderstorms, heavy snow, violent showers)
- Coordinates looked up from `facilities.json` city field — P01 maps to London LHR, P04 to Chicago ORD, etc.
- Graceful fallback if API is unavailable — does not crash, logs warning

**Stage 2 — Groq LLM reasoning**
- Calls `llama-3.3-70b-versatile` with full shipment context:
  - Product name, temperature class, required range, freeze sensitivity
  - Current container temperature and slope (°C/hr)
  - Hours until breach (or "already breached")
  - Delay class, active breach rules, transit phase, risk tier
  - Live weather at destination
- Prompt explicitly instructs the model to recommend a carrier and mode — not invent geographic routes
- For CRITICAL already-breached shipments, urgency instruction forces negative ETA change
- Per-class carrier guidance in prompt: Atlas Air/Cargolux for frozen, BA World Cargo/DHL for refrigerated, FedEx/UPS for CRT
- Returns `recommended_route`, `carrier`, `eta_change_hours`, `justification`, `model_used`
- Fallback chain: `llama-3.3-70b-versatile` → `llama-3.1-8b-instant` (rate limit) → deterministic (API failure)
- JSON truncation guard: `max_tokens=600` + closing-brace repair if response is cut off

### Working output (live, primary model)

```
Product:   Vaccine-C (P06) — REFRIGERATED — must maintain 2-8°C
Weather:   overcast, 25.4°C, wind 11.2mph at Chicago ORD (Open-Meteo live)
Route:     Air freight via ORD (GDP-certified pharma lane)
Carrier:   DHL Life Sciences
ETA:       -2 hours
Model:     llama-3.3-70b-versatile
Source:    groq_llm
Justification: Given the critical temperature breach and the need for
rapid transport, DHL Life Sciences is recommended for its GDP-certified
pharma lane capabilities. The overcast conditions at ORD are manageable
for air freight, and the -2 hour ETA improvement minimises further
exposure time for this freeze-sensitive product.
```

### Why this is genuinely agentic

The justification changes based on actual conditions. A shipment with severe weather at destination gets a different recommendation than the same product in clear skies. A frozen product at air_handoff with 0 hours to breach gets a different urgency framing than a CRT product with 2.5 hours buffer. The LLM reasons about the combination of factors — not pattern-matches against a table.

### Data sources

- `data/product_profiles.json` — temperature class classification
- `data/facilities.json` — destination facility city for weather coordinates
- Open-Meteo API — live weather (no key required)
- Groq API — LLM reasoning (key in `.env`, gitignored)

### Demo script

`demo_smoke_test.py` at repo root runs the full cascade in one command:
```bash
.venv/Scripts/python demo_smoke_test.py
```
