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
