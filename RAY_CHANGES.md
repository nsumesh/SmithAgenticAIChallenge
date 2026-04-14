# Ray's Agent Improvements — Change Log
**Branch:** ray/agent-improvements
**Started:** 2026-04-09
**Purpose:** Improve route_agent, insurance_agent, and fix audit log bug before team pitch.
**Rollback:** `git checkout develop` restores original state at any time.

---

## Change 1 — Audit Log Bug Fix
**File:** `backend/app.py`
**Line:** ~436 (_load_audit_records function)
**Problem:** compliance_agent writes to `compliance_events.jsonl` but _load_audit_records() only globs `audit_*.jsonl`. Compliance tool events are invisible to the AuditLog frontend view.
**Fix:** Expand glob to also read `compliance_events.jsonl`
**Risk:** Low — additive only, no existing behavior broken
**Status:** PENDING

---

## Change 2 — Route Agent: Real Data Routing
**File:** `tools/route_agent.py`
**Problem:** Uses random.choice over 4 hardcoded strings. Ignores location_hint, preferred_mode, product_id. Frozen vaccine gets same route as CRT medicine.
**Fix:** Load facilities.json + product_profiles.json, select route based on product temp class, destination facility location, and preferred_mode. Remove random.choice entirely.
**Risk:** Medium — changes tool return values; cascade enrichment in nodes.py reads recommended_route and carrier fields, both preserved
**Status:** PENDING

---

## Change 3 — Insurance Agent: Tighten Loss Calculation
**File:** `tools/insurance_agent.py`
**Problem:** Already reads real data (scored_windows.csv + product_costs.json) but loss formula and claim assembly can be made more specific to the actual excursion data.
**Fix:** TBD after reviewing full file content
**Risk:** Low
**Status:** PENDING

---

## Proposed Addition — RAG Layer for Compliance + Route Context
**Files:** New file `src/rag_retriever.py`, modifications to `src/context_assembler.py`
**Purpose:** Semantic retrieval of GDP/FDA/WHO regulatory text to make compliance reasoning real instead of hardcoded strings. Shared by compliance_agent (teammate) and route_agent (Ray).
**Vector store:** ChromaDB (local, no API key needed) with fallback path to Pinecone if team upgrades
**Status:** PROPOSED — needs team alignment before implementation

---
*All changes on branch ray/agent-improvements. To rollback everything: `git checkout develop`*
*To rollback a single file: `git checkout develop -- <filepath>`*

---

## IMPLEMENTATION STATUS (updated 2026-04-09)

### Change 1 — Audit Log Bug Fix: DONE
- Modified `_load_audit_records` to glob both `audit_*.jsonl` AND `compliance_events.jsonl`
- Both audit streams now visible to frontend AuditLog view

### Change 2 — Insurance Agent Downstream Disruption: DONE
- Added `_load_facilities()` to insurance_agent.py
- `_aggregate_leg_history()` now accepts `product_id` and returns real `appointment_count` from facilities.json
- `_compute_loss_breakdown()` now receives real appointment_count so `downstream_disruption_usd` is no longer always $0

### Change 3 — Route Agent Context-Aware Routing: DONE
- Removed `random.choice` entirely
- Routes now selected by product temp class (frozen/refrigerated/CRT) from product_profiles.json
- Urgent/critical reasons sort options by fastest ETA delta
- `product_id` added as optional field to RouteInput schema (backward compatible — old callers without product_id fall back to 'refrigerated')
- Output dict keys unchanged: cascade in nodes.py unaffected

### Change 4 — Wire product_id to route_agent in orchestrator: DONE
**File:** `orchestrator/nodes.py`
**Line:** ~228 (_build_tool_input route_agent block)
**Problem:** product_id was never passed to route_agent tool input. Every real orchestrated call fell back to 'refrigerated' temp class regardless of actual product (P04 frozen vaccine got same route as P01 refrigerated).
**Fix:** Added `"product_id": ri.get("product_type", "")` to the route_agent input dict.
**Verified:** P04 now correctly gets frozen routes (Atlas Air Cold Chain) through the real orchestrator path.

### Change 5 — Fix triage_agent KeyError: DONE
**File:** `tools/triage_agent.py`
**Line:** ~41
**Problem:** Hard dict access s["container_id"] and s["transit_phase"] crashed when called with raw dicts missing those optional fields.
**Fix:** Changed to .get() with empty string defaults throughout _execute.
**Verified:** Works with both minimal dicts and full dicts. Tier ordering correct.

### Rollback
- Per-file: `git checkout develop -- tools/route_agent.py` etc.
- Full rollback: `git checkout develop`
- Backup files: `*.bak` copies exist in each directory
