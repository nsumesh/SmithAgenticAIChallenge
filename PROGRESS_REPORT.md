# AI Cargo Monitoring -- Progress Report & Task Distribution

## System Layers

```
L1   Data Pipeline (Supabase)         DONE   Karthik (gen/stream) + Rahul (integration)
L2   Risk Scoring Engine              DONE   Rahul
L3   Agent Tools (8 tools)            DONE   Mukul (route/insurance/triage) + Nikhil (cascade)
                                              + Yash (RAG compliance) + Rahul (framework)
L4   Orchestration Agent (Agentic)    DONE   Rahul (Groq LLM + deterministic fallback)
L5   Multi-Provider LLM System        DONE   Rahul (Groq/Ollama/OpenAI/Anthropic)
L6   Context Assembler                DONE   Nikhil (cascade context builder)
L7   RAG Compliance Sub-System        DONE   Yash (pgvector + embeddings + LLM)
L8   FastAPI Backend (25 endpoints)    DONE   Rahul + Mukul (triage endpoints)
L9   React Dashboard                  DONE   Rahul
L10  Integration + E2E Tests          DONE   Rahul
```

---

## Data Flow (End-to-End)

```
SUPABASE CLOUD
┌──────────────────────────────────────────────────────────────────────────┐
│ window_features (7,411) │ product_profiles (6) │ facilities (6)         │
│ product_costs (6)       │ compliance_knowledge (pgvector)               │
│                         │ compliance_docs (Storage bucket: PDFs)         │
└──────────┬──────────────┴──────────────────────┬─────────────────────────┘
           │                                     │
           │  src/supabase_client.py              │  tools/helper/vector_store.py
           │  (paginated fetch, local fallback)   │  (semantic search via pgvector)
           ▼                                     ▼
  ┌─────────────────┐                    ┌────────────────────┐
  │ src/data_loader  │                    │ compliance_agent   │
  │ load_raw()       │                    │ (RAG validation)   │
  └────────┬────────┘                    └────────────────────┘
           │
           ▼
  pipeline.py (LangGraph)
  ├── feature_engineering.py   → 14 derived features
  ├── deterministic_engine.py  → 8 product-aware rules → det_score
  ├── predictive_model.py      → XGBoost + Optuna → ml_probability + SHAP
  ├── risk_fusion.py           → final = 0.4×det + 0.6×ML → risk_tier
  └── compliance_logger.py     → audit_logs/audit_YYYYMMDD.jsonl
           │
           ▼
  context_assembler.py         → delay_ratio, delay_class, hours_to_breach
           │
           ▼
  orchestrator/graph.py        → LangGraph StateGraph
  interpret → plan(LLM) → reflect(LLM) → [revise(LLM)] → approval_gate
                                              ├── MEDIUM: execute → observe → output (auto)
                                              └── HIGH/CRITICAL: output (plan-only, awaiting human)
  After approval: run_orchestrator_selective → execute → observe → output
           │
           │  execute() calls tools sequentially with cascade enrichment
           ▼
  8 Agent Tools: compliance → cold_storage → notification → insurance
                 → scheduling → route → triage → approval_workflow
           │
           ▼
  backend/app.py (FastAPI)     → 25 REST endpoints + WebSocket
           │
           ▼
  dashboard/ (React)           → 8 pages: Overview, Monitoring, Shipments,
                                  ShipmentDetail, AgentActivity, GraphView,
                                  AuditLog, Approvals
```

**Data sources**: All tools and the data loader try Supabase first, fall back to local JSON/CSV.

**Real-time path**: `stream_listener.py` subscribes to Supabase Realtime on `window_features` table,
forwards new rows to `POST /api/ingest` which runs single-window scoring + orchestration.

---

## Agent & Tool Registry

Every agent is a **LangChain StructuredTool** with a Pydantic input schema.
The orchestrator invokes them via `tool.invoke(input_dict)`.

### Tool Summary Table

| # | Agent | File | Purpose | Data Source | Owner |
|---|-------|------|---------|-------------|-------|
| 1 | **compliance_agent** | `tools/compliance_agent.py` | **RAG-powered** regulatory validation: semantic search over FDA/WHO/ICH/GDP regulations via Supabase pgvector + Groq LLM interpretation. Returns compliance status, violations, disposition, approval level, citations. Immutable audit log. Falls back to mock regs + deterministic if LLM/vector unavailable. | Supabase `compliance_knowledge` (pgvector) + mock fallback | **Yash** (RAG core) + **Rahul** (integration, async fix, cascade enrichment) |
| 2 | **route_agent** | `tools/route_agent.py` | **Hybrid route recommendation**: looks up product temp class (frozen/refrigerated/CRT), builds safe carrier candidates from `_ROUTE_TABLE`, lets the active LLM choose among them when available, then falls back to deterministic urgency sorting | Supabase `product_profiles` + local fallback | **Mukul** + **Rahul** |
| 3 | **cold_storage_agent** | `tools/cold_storage_agent.py` | Finds backup cold-storage: scores all facilities by temp compatibility × distance × capacity × urgency, returns top candidate + alternatives | Supabase `facilities` + `product_profiles` + local fallback | **Nikhil** (facility data) + **Rahul** (Supabase) |
| 4 | **notification_agent** | `tools/notification_agent.py` | Multi-channel alerts: builds alert payload with revised ETA, spoilage probability, facility name (from cascade). Payload-only, no external delivery yet | (none -- payload construction only) | **Nikhil** (cascade enrichment) |
| 5 | **scheduling_agent** | `tools/scheduling_agent.py` | Facility reschedule: generates per-facility recommendations with routing decisions, priority scoring, financial impact estimates, compliance flags | Supabase `facilities` + `product_costs` + local fallback | **Nikhil** (rich routing) |
| 6 | **insurance_agent** | `tools/insurance_agent.py` | Claim preparation: itemized loss breakdown (product + disposal + handling + downstream disruption), leg excursion history from scored_windows.csv | `scored_windows.csv` + Supabase `product_costs` + `facilities` | **Mukul** (appointment_count fix) |
| 7 | **triage_agent** | `tools/triage_agent.py` | Multi-shipment ranking: enriches with hours_at_risk, peak_temp, breach_rule from scored_windows.csv, returns priority-ordered list | `scored_windows.csv` + Supabase `product_profiles` | **Mukul** (enrichment) |
| 8 | **approval_workflow** | `tools/approval_workflow.py` | Human-in-the-loop: creates pending approval request with consolidated action summaries from cascade | In-memory `_PENDING_APPROVALS` dict | **Rahul** |

### Tool Input/Output Quick Reference

| Tool | Key Inputs | Key Outputs |
|------|-----------|-------------|
| **compliance_agent** | `risk_tier, details{product_category, current_temp_c, minutes_outside_range, spoilage_probability}` | `compliance_status, product_disposition, approval_level, violations[], log_id, decision_method` |
| **route_agent** | `product_id, reason, current_leg_id` | `recommended_route, carrier, eta_change_hours, temp_class, selection_method, selection_rationale` |
| **cold_storage_agent** | `product_id, urgency, location_hint, hours_to_breach` | `recommended_facility, suitability_score, advance_notice_required_hours, temp_range_supported` |
| **notification_agent** | `risk_tier, recipients[], message, channel` | `status:"notification_queued", alert_payload, delivered:false` |
| **scheduling_agent** | `product_id, affected_facilities[], original_eta, delay_class, hours_to_breach` | `routing_decision, priority_score, financial_impact_estimate_usd, facility_recommendations[]` |
| **insurance_agent** | `product_id, risk_tier, spoilage_probability, estimated_loss_usd` | `claim_id, loss_breakdown{product, disposal, handling, disruption}, next_steps[]` |
| **triage_agent** | `shipments[{shipment_id, risk_tier, fused_risk_score}]` | `priority_list[], recommended_orchestration_order[], critical_count` |
| **approval_workflow** | `action_description, risk_tier, urgency, proposed_actions[]` | `approval_id, status:"approval_requested"` |

### How Tools Connect to the Orchestrator

```
AGENTIC MODE (Groq LLM available):
  orchestrator/llm_nodes.py :: plan_llm()
      │ LLM (Groq llama-3.3-70b-versatile) analyzes risk event
      │ LLM selects tools AND constructs input payloads with domain reasoning
      │ Falls back to deterministic templates if LLM output is malformed
      ▼
  orchestrator/llm_nodes.py :: reflect_llm()
      │ LLM critiques plan: checks for compliance, notification, approval gaps
      │ Outputs "GAP [name]: ..." notes that trigger revise
      ▼
EXECUTION (shared by both modes):
  orchestrator/nodes.py :: execute()
      │ for each step in active_plan:
      │   base_input = step["tool_input"]           ← from LLM or template
      │   enriched = _enrich_tool_input(...)         ← cascade enrichment
      │   result = TOOL_MAP[tool_name].invoke(enriched)
      │   cascade_ctx[tool_name] = result            ← feeds downstream tools
      ▼
CASCADE ENRICHMENT:
  compliance result  ──→  insurance_agent gets log_id as supporting_evidence
  cold_storage result ──→  notification_agent gets facility_name, advance_notice
  cold_storage result ──→  scheduling_agent gets facility, advance_notice, temp_range
  product_cost data  ──→  insurance_agent gets estimated_loss_usd
  all tool results   ──→  approval_workflow gets consolidated action summaries
  risk_input fields  ──→  compliance_agent gets full details (product, temp, phase, etc.)
```

---

## Orchestration Agent -- Node-by-Node

| Node | File:Function | Mode | What it does | Output State Keys |
|------|--------------|------|-------------|-------------------|
| **interpret** | `nodes.py :: interpret_risk()` | Deterministic | Parses risk JSON, maps tier to severity/urgency, identifies primary issue from rule flags | `severity, urgency, primary_issue` |
| **plan** | `llm_nodes.py :: plan_llm()` | **Agentic** (Groq) | LLM reasons about situation, selects tools, constructs inputs. GDP/FDA/WHO domain knowledge in system prompt. Token-efficient tool schemas. Falls back to deterministic if unparseable. | `draft_plan, llm_reasoning, requires_approval` |
| **plan** | `nodes.py :: plan()` | Deterministic | Tier templates: CRITICAL→6 tools, HIGH→4, MEDIUM→2, LOW→0. Adds route_agent for air_handoff/customs. `_build_tool_input()` constructs payloads from risk_input. | `draft_plan, requires_approval` |
| **reflect** | `llm_nodes.py :: reflect_llm()` | **Agentic** (Groq) | LLM checks plan against 6+ compliance requirements. Outputs "OK" or "GAP [name]:" notes. | `reflection_notes` |
| **reflect** | `nodes.py :: reflect()` | Deterministic | 5-point checklist: compliance_covered, notification_included, approval_for_irreversible, has_fallback, no_empty_steps | `reflection_notes` |
| **revise** | `llm_nodes.py :: revise_llm()` | **Agentic** (Groq) | LLM rewrites full plan + `tool_input` from draft + reflection gaps; falls back to deterministic revise if LLM disabled or malformed. | `revised_plan, active_plan, plan_revised` |
| **revise** | `nodes.py :: revise()` | Deterministic | Keyword scan on GAP notes → inserts missing tools (compliance at pos 0, approval last, others appended). Supports: compliance, notification, insurance, cold_storage, scheduling, approval | `revised_plan, active_plan, plan_revised` |
| **approval_gate** | `graph.py :: _approval_gate()` | Deterministic | Creates approval request and PAUSES pipeline for HIGH/CRITICAL. MEDIUM proceeds to execute. Stores proposed tools from the plan. | `requires_approval, approval_id, awaiting_approval` |
| **execute** | `nodes.py :: execute()` | Deterministic | Sequential tool invocation with cascade enrichment; `_DEPENDS_ON`-aware warnings when upstream tools fail; `failed_tools` tracking; per-tool errors do not abort the chain. | `tool_results, execution_errors, cascade_context, approval_id` |
| **observe** | `llm_nodes.py :: observe_llm()` | **Agentic** (Groq) | LLM inspects execution results, decides if re-planning is needed for CRITICAL failures. | `observation, needs_replan, observation_issues, observation_actions` |
| **fallback** | `nodes.py :: build_fallback()` | Deterministic | Minimal backup: notification_agent + compliance_agent | `fallback_plan` |
| **output** | `nodes.py :: compile_output()` | Deterministic | Assembles final JSON with LLM reasoning, cascade context (full + 200-char summary), confidence score | `final_output, decision_summary, confidence` |

### Conditional Edges

```
reflect ──→ revise          (if "GAP" found in notes AND not already revised)
reflect ──→ approval_gate   (if plan passes all checks)
reflect ──→ output          (if tier is LOW → skip everything)
approval_gate ──→ execute   (MEDIUM tier: auto-execute)
approval_gate ──→ output    (HIGH/CRITICAL: plan-only, awaiting human approval)
observe ──→ replan_bridge   (if needs_replan=True AND replan_count < 1, CRITICAL only)
observe ──→ fallback→output (otherwise — finalize results)
```

---

## LLM Provider System

| Provider | Model | Speed | Status | Env Vars |
|----------|-------|-------|--------|----------|
| **Groq** (default) | `llama-3.3-70b-versatile` | ~1-2s per call | **ACTIVE** — primary provider | `GROQ_API_KEY`, `CARGO_GROQ_MODEL` |
| Ollama | `qwen2.5:7b` | ~5-10s per call | Fallback (local, free) | `CARGO_OLLAMA_MODEL` |
| OpenAI | `gpt-4o-mini` | ~2-3s per call | Slot available | `OPENAI_API_KEY`, `CARGO_OPENAI_MODEL` |
| Anthropic | `claude-3-5-haiku-latest` | ~2-3s per call | Slot available | `ANTHROPIC_API_KEY`, `CARGO_ANTHROPIC_MODEL` |

**Configuration**: `CARGO_LLM_PRIORITY=groq,ollama,openai,anthropic` in `.env`
**Disable**: `CARGO_LLM_ENABLED=0` for deterministic-only mode
**Hot-switch**: `POST /api/llm/configure` changes provider at runtime without restart
**Caching**: Provider is cached; graph recompiles automatically on provider change

---

## RAG Compliance Sub-System (Yash)

```
tools/helper/                          ← NEW: helper modules for compliance RAG
├── vector_store.py                    Supabase pgvector client (compliance_knowledge)
│                                      Falls back to MockComplianceVectorStore
├── mock_vector_store.py               6 hardcoded FDA/ICH/WHO/GDP regulations
│                                      Keyword-overlap scoring (no embeddings needed)
├── embeddings.py                      SentenceTransformer (all-MiniLM-L6-v2, dim=384)
│                                      Batch encode + cosine similarity
├── llm_interpreter.py                 Groq LLM for edge-case compliance scenarios
│                                      (conflicting rules, borderline decisions)
├── document_parser.py                 PDF → chunked text (500 words, 50 overlap)
│                                      Section detection via regex headers
├── ingest_compliance_docs.py          Supabase Storage → parse PDF → embed → INSERT
│                                      7 regulatory documents configured (WHO, EU GDP,
│                                      FDA 21 CFR 11, ICH Q9, PIC/S GDP, IATA Vaccine)
└── mocks.py                           MockComplianceAgent for testing without LLM

Compliance Agent Workflow:
  1. AUDIT LOG      → always write to compliance_events.jsonl (immutable, GDP)
  2. SEMANTIC SEARCH → query pgvector via match_compliance_documents() RPC
                       fallback: brute-force cosine in Python
                       fallback: mock regulations (6 hardcoded)
  3. LLM INTERPRET  → Groq llama-3.3-70b reads regulations + shipment context
                       → JSON: decision, severity, disposition, violations, reasoning
                       fallback: deterministic tier-based ruling
  4. OUTPUT         → compliance_status, violations[], product_disposition,
                       approval_level, citations[], decision_method
```

---

## Backend API Endpoints (25 + WebSocket)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/risk/overview` | GET | Tier distribution, KPIs, top risky shipments |
| `/api/shipments` | GET | All shipments, filterable by `risk_tier` |
| `/api/shipments/{id}/windows` | GET | All windows for a shipment |
| `/api/windows` | GET | Windows, filterable by tier/product, paginated |
| `/api/windows/{window_id}` | GET | Single window detail |
| `/api/risk/score-window/{id}` | GET | Risk engine output for orchestrator |
| `/api/ingest` | **POST** | **Real-time single-window scoring** (from Supabase stream) |
| `/api/orchestrator/run/{id}` | POST | Run orchestration agent on a window |
| `/api/orchestrator/run-batch` | POST | Orchestrate multiple windows |
| `/api/orchestrator/history` | GET | Recent orchestrator decisions (bounded to 500) |
| `/api/orchestrator/history` | DELETE | Clear in-memory orchestration history |
| `/api/approvals/all` | GET | All approval requests (pending + approved + rejected) |
| `/api/approvals/{id}/execute` | POST | Execute approved plan with human-selected tools (skips approval_workflow) |
| `/api/orchestrator/mode` | GET | Current mode (agentic/deterministic) + provider + model |
| `/api/tools/{name}/execute` | POST | Execute any agent tool directly |
| `/api/triage/critical-shipments` | **GET** | **Auto-triage**: pull worst shipments, rank with enrichment |
| `/api/triage/rank` | **POST** | **Rank caller-supplied shipments** |
| `/api/graph/mermaid` | GET | Orchestrator graph as Mermaid string |
| `/api/graph/topology` | GET | Full 5-layer system topology JSON |
| `/api/audit-logs` | GET | Compliance audit records (audit + compliance_events) |
| `/api/approvals/pending` | GET | Pending human approval requests |
| `/api/approvals/{id}/decide` | POST | Approve or reject an action |
| `/api/llm/status` | GET | Active LLM provider, available providers, config |
| `/api/llm/configure` | POST | Hot-configure API keys, priority, models |
| `/ws/events` | WebSocket | Real-time event stream |

---

## Task Ownership

### Rahul -- Risk Engine, Orchestrator, Backend, Dashboard, Integration

| # | Task | Status |
|---|------|--------|
| 1 | Synthetic data audit & EDA notebook | DONE |
| 2 | Product profiles (WHO-aligned thresholds for 6 products) | DONE |
| 3 | Feature engineering module (14 derived features) | DONE |
| 4 | Deterministic rule engine (8 rules including freeze risk) | DONE |
| 5 | Predictive ML model (XGBoost + Optuna + SHAP) | DONE |
| 6 | Risk fusion layer (alpha-blend + veto + NaN handling) | DONE |
| 7 | Compliance logger (GDP/FDA JSONL audit records) | DONE |
| 8 | LangGraph risk-scoring pipeline (train/score modes) | DONE |
| 9 | Agent tools framework (8 LangChain tools, registry, schemas) | DONE |
| 10 | FastAPI backend (25 endpoints + WebSocket) | DONE |
| 11 | React dashboard (8 pages with Recharts, Mermaid, Tailwind) | DONE |
| 12 | **Agentic orchestration** (Groq LLM plan + reflect nodes, domain prompts) | DONE |
| 13 | **Multi-provider LLM system** (Groq/Ollama/OpenAI/Anthropic with hot-switch) | DONE |
| 14 | **Supabase data pipeline integration** (supabase_client.py, all 5 tables) | DONE |
| 15 | **Karthik changes integration** (stream_listener, simulate_stream, /api/ingest, fixed `window_features` table wiring) | DONE |
| 16 | **Mukul changes integration** (route/insurance/triage agents, triage API) | DONE |
| 17 | **Nikhil changes integration** (cascade enrichment, context assembler, facility data) | DONE |
| 18 | **Yash RAG compliance integration** (fix async deadlock, create MockVectorStore, cascade enrichment for compliance details, install sentence-transformers) | DONE |
| 19 | Deep audit & bug fixes (NaN handling, cache management, SHAP alignment, bounded history) | DONE |
| 20 | E2E tests across all tiers (agentic + deterministic + API) | DONE |
| 21 | Documentation (README, ARCHITECTURE, PROGRESS_REPORT) | DONE |

### Karthik -- Data Pipeline & Supabase

| # | Task | Status |
|---|------|--------|
| K1 | Synthetic data generator (physics-based + API-based) | DONE |
| K2 | Supabase table setup (window_features, product_profiles, product_costs, facilities) | DONE |
| K3 | Stream simulator (CSV replay → Supabase inserts via simulate_stream.py) | DONE |
| K4 | Realtime listener (Supabase Realtime → POST /api/ingest HTTP bridge) | DONE |

### Mukul -- Route, Insurance, Triage Agents

| # | Task | Status |
|---|------|--------|
| M1 | Route agent: replaced random.choice with _ROUTE_TABLE keyed by temp class + urgency | DONE |
| M2 | Route agent: LLM-assisted choice among safe candidate routes with deterministic fallback | DONE |
| M3 | Orchestrator: wired product_id to route_agent via _build_tool_input | DONE |
| M4 | Insurance agent: fixed appointment_count from facilities → real downstream_disruption | DONE |
| M5 | Triage agent: _enrich_shipment() from scored_windows.csv + urgency labels + orchestration order | DONE |
| M6 | Backend: triage API endpoints (critical-shipments, rank) + audit log glob fix | DONE |

### Yash -- RAG Compliance Agent

| # | Task | Status |
|---|------|--------|
| Y1 | VectorComplianceAgent core (semantic search + LLM interpretation workflow) | DONE |
| Y2 | Supabase pgvector integration (compliance_knowledge table, match_compliance_documents RPC) | DONE |
| Y3 | Sentence-transformers embedding generator (all-MiniLM-L6-v2, 384 dimensions) | DONE |
| Y4 | Compliance document parser (PDF → section detection → 500-word chunks with overlap) | DONE |
| Y5 | Ingestion script (Supabase Storage bucket → download PDF → parse → embed → INSERT) | DONE |
| Y6 | Mock vector store fallback (6 hardcoded FDA/ICH/WHO/GDP regulations for offline use) | DONE |
| Y7 | ComplianceLLMInterpreter for edge-case compliance (conflicting rules, borderline scenarios) | DONE |
| Y8 | Notification agent architecture design (agentic stakeholder selection, channel strategy) | DONE |

### Nikhil -- Cascade Enrichment & Context Assembler

| # | Task | Status |
|---|------|--------|
| N1 | Context assembler (compute_delay_ratio, compute_delay_class, compute_hours_to_breach) | DONE |
| N2 | Cascade execution (_enrich_tool_input: cold_storage→notification, compliance→insurance) | DONE |
| N3 | Enriched facilities.json + product_costs.json with real facility/cost data | DONE |
| N4 | Insurance/notification/scheduling cascade enrichment (revised ETA, facility, advance notice) | DONE |

---

## Red Flags & Current Limitations

### Security Issues (must fix before production)

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | **Unauthenticated `/api/llm/configure`** — anyone can change LLM API keys | CRITICAL | Open |
| 2 | **No authentication on any API endpoint** — all endpoints are public | CRITICAL | Open |
| 3 | **CORS `allow_origins=["*"]`** with `allow_credentials=True` | HIGH | Open |
| 4 | **Supabase anon key in .env** — using anon role (RLS-dependent) | MEDIUM | Open |
| 5 | **WebSocket unauthenticated** — any client can subscribe to events | MEDIUM | Open |

### Functional Gaps

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 6 | **Notification agent does not deliver** — builds payload but `delivered=False` | MEDIUM | Open (integrate Twilio/SendGrid) |
| 7 | **Route geography is static** — selects by temp class, not real origin/destination | MEDIUM | Open (no origin/dest in dataset) |
| 8 | **Streaming bridge was still pointed at old `telemetry` table** — `stream_listener.py` and `simulate_stream.py` would miss new `window_features` inserts | HIGH | Fixed |
| 9 | **`shock_count` 99.7% zeros / `door_open_count` 99.8% zeros** in data | LOW | Open (improve data generation) |
| 10 | **Approval workflow is in-memory** — pending approvals lost on server restart | LOW | Open (persist to Supabase) |
| 11 | **Approval→execution gap** — ~~when operator approves, nothing happens~~ Plan-first HITL: HIGH/CRITICAL stop at `approval_gate` with plan-only output; `POST /api/approvals/{id}/execute` runs `run_orchestrator_selective` so tools run **once** after approval (no double-execution; `approval_workflow` is not part of the automated execute chain). WebSocket broadcasts `approval_executed` events. Agent Activity and Approvals tabs sync via `useWebSocket` hook. | HIGH | **Fixed** |
| 12 | **No human tool selection** — ~~operator can only approve/reject~~ Approvals page now has toggle buttons for each tool. Operator can select specific tools before clicking Execute. `run_orchestrator_selective()` runs only the chosen tools. | MEDIUM | **Fixed** |
| 13 | **Execute node is fire-and-forget** — ~~runs all tools sequentially without checking~~ Execute now tracks `failed_tools` set, injects warnings into downstream tools when upstream dependencies fail (e.g. cold_storage→notification), and uses `_DEPENDS_ON` map for dependency awareness. | MEDIUM | **Fixed** |
| 14 | **Single-iteration plan-reflect loop** — ~~graph never loops back after execution~~ Observe node (LLM-powered) inspects execution results and triggers re-plan for CRITICAL events if tools failed. Max 1 re-plan iteration to prevent infinite loops. | HIGH | **Fixed** |
| 15 | **Revise node was keyword matching** — ~~str.find() for gap detection~~ Now `revise_llm()` sends draft plan + reflection notes + shipment context to Groq LLM, which rewrites the full plan with missing tools and correct inputs. Falls back to deterministic revise if LLM unavailable. | HIGH | **Fixed** |

---

## Tool-by-Tool Intelligence Analysis (Code-Verified, Unbiased)

### Honest Assessment: What Is and Isn't Agentic

**Bottom line: 2 out of 8 tools use LLM/AI. The other 6 are deterministic functions
with "agent" in the name.**

The system's agentic behavior lives in the **orchestration layer**, not in the tools.
The Groq LLM in `plan_llm()` selects tools and constructs inputs, and `reflect_llm()`
self-critiques the plan. This is a **tool-use agent** pattern (similar to ReAct) — the
LLM is the brain, the tools are the hands. But we need to be precise about limitations:

**What IS agentic:**
- `plan_llm()` — LLM reasons about which tools to call and why (genuine reasoning)
- `reflect_llm()` — LLM critiques its own plan against GDP/FDA compliance (self-correction)
- `revise_llm()` — LLM rewrites the plan to fix all gaps from reflection (LLM plan editing)
- `observe_llm()` — LLM inspects execution results and decides if re-planning is needed (feedback loop)
- `_approval_gate()` — creates approval and pauses execution for human review (HITL gate)
- `compliance_agent` — RAG semantic search + LLM interprets real regulations (novel judgments)
- `route_agent` — LLM evaluates trade-offs among pre-filtered safe candidates

**What is NOT agentic (and we should be honest about it):**
- `execute()` — sequential tool invocation. Now dependency-aware (tracks `failed_tools`,
  injects warnings when upstream fails), but still runs in a fixed order without dynamic
  reordering. (nodes.py)
- `cold_storage_agent` — weighted scoring formula with hardcoded weights. No reasoning.
- `scheduling_agent` — feasibility checks and priority formula. Deterministic arithmetic.
- `insurance_agent` — `unit_cost × units × spoilage_probability + disposal + handling`.
  Every number traces to product_costs.json. No intelligence.
- `notification_agent` — assembles a dict from its inputs. Payload construction.
- `triage_agent` — `sort(key=tier_order, then -score)`. A two-key sort.
- `approval_workflow` — stores a dict in `_PENDING_APPROVALS`. Now supports post-approval
  execution with human tool selection, but the approval mechanism itself is a state machine.

**Remaining limitations:**
- The LLM picks tools from a **fixed menu of 8**. It cannot discover, compose, or create
  new tools. The tool schemas are hardcoded in the system prompt.
- Cascade enrichment is **hardcoded**: `if tool_name == "compliance_agent": details.setdefault(...)`
  — there are explicit per-tool enrichment blocks in `_enrich_tool_input()`.
  The agent doesn't decide what context to pass; the code does.
- Re-plan loop is capped at **1 iteration** (MAX_REPLAN=1). A fully autonomous agent could
  iterate until convergence. We cap it to prevent runaway LLM calls and cost overruns.

**Why deterministic tools are defensible (but not "agentic"):**
In pharmaceutical cold-chain, regulators require auditable, reproducible decisions.
An LLM hallucinating a $39K insurance claim would be challenged in court. Facility
scoring must produce identical outputs for identical inputs. This is a valid
architecture — but calling these tools "agents" is a stretch. They are **deterministic
utility functions** invoked by an agentic orchestrator.

### Detailed Breakdown

#### 1. compliance_agent — AGENTIC (RAG + LLM)

**How it works (code: `tools/compliance_agent.py`)**:
```
Query → EmbeddingGenerator (all-MiniLM-L6-v2)
      → pgvector semantic search (compliance_knowledge, 417 docs)
      → Top-K regulatory chunks retrieved
      → Groq LLM (llama-3.3-70b-versatile) interprets regulations
      → JSON: compliance_status, violations[], disposition, citations[]
```
- `decision_method` output tracks: `vector_search_llm`, `deterministic_fallback`, `mock_regs_*`
- Three fallback layers: pgvector → brute-force cosine → mock regulations → deterministic
- Always writes immutable JSONL audit log regardless of method
- **Agentic because**: The LLM reads actual regulatory text and reasons about whether
  a specific temperature excursion violates WHO TRS 961 Annex 9 or ICH Q1A guidelines.
  It produces novel compliance judgments, not template lookups.

#### 2. route_agent — HYBRID (LLM + Rules)

**How it works (code: `tools/route_agent.py`)**:
```
product_id → _get_temp_class() → frozen/refrigerated/crt  (deterministic)
temp_class + mode → _ROUTE_TABLE lookup → candidate routes  (deterministic)
candidates + context → get_llm().invoke(prompt)             (agentic)
  LLM returns: selected_index + rationale (JSON)
  Fallback: _select_route_rule_based() sorts by ETA delta   (deterministic)
```
- `selection_method` output tracks: `llm` or `rule_based`
- Candidates are **pre-filtered for safety** (only certified carriers for the temp class)
- The LLM never sees unsafe options — it picks the best among safe ones
- **Agentic because**: The LLM evaluates trade-offs (speed vs cost vs reliability)
  that can't be captured in a simple sort. `selection_rationale` is a novel explanation.

#### 3. cold_storage_agent — DETERMINISTIC (Weighted Scoring)

**How it works (code: `tools/cold_storage_agent.py`)**:
```
facilities.json (or Supabase) → for each facility:
  _check_temp_compatibility(product temp range vs facility range)  → pass/fail gate
  _score_facility():
    0.30 × capacity_score        (higher remaining capacity = better)
    0.25 × proximity_score       (closer to location_hint = better)
    0.20 × notice_score          (advance_notice_hours vs hours_to_breach)
    0.15 × certification_score   (GDP, FDA, AABB, etc.)
    0.10 × emergency_score       (accepts_emergency_delivery flag)
  → Sort by disqualified first, then by score descending
  → Top = recommended, rest = alternatives with disqualification reasons
```
- Hard gate: if product needs 2–8°C and facility only supports 15–25°C → disqualified
- `suitability_tier`: ≥0.7 = excellent, ≥0.5 = good, ≥0.3 = acceptable, else marginal
- **Why deterministic is correct**: Facility selection must be reproducible and auditable.
  A regulator asking "why did you pick this facility?" needs a traceable scoring formula,
  not "the LLM thought it was good."

#### 4. notification_agent — DETERMINISTIC (Payload Assembly)

**How it works (code: `tools/notification_agent.py`)**:
```
Inputs (risk_tier, message, recipients, channel, cascade data)
  → Assemble alert_payload dict with revised_eta, spoilage_probability, facility_name
  → Set requires_approval = (risk_tier in HIGH, CRITICAL)
  → Return status: "notification_queued", delivered: false
```
- Does NOT actually send notifications — builds the payload for external delivery
- Cascade enrichment provides: facility name from cold_storage, ETA from scheduling
- **Why deterministic is correct**: Notification content must exactly reflect the data.
  LLM rewording risks misrepresenting spoilage probability or ETA.

#### 5. scheduling_agent — DETERMINISTIC (Feasibility + Priority Matrix)

**How it works (code: `tools/scheduling_agent.py`)**:
```
For each affected facility:
  _check_facility_feasibility():
    advance_notice_hours vs time_to_eta → feasible/infeasible
    occupancy > 85% → capacity_constrained
    operating_hours vs timezone → arrival_during_hours check
    urgency → emergency_contact vs standard contact
  _resolve_facility_routing():
    primary feasible + backup feasible → "primary"
    primary infeasible + backup feasible → "backup"
    both feasible, primary constrained → "split"
    none feasible → "no_feasible_option"
  _rank_appointment_priority():
    (unit_cost × units) / 1000 + {critical:40, high:25, medium:10, low:0}
  financial_impact = disruption_per_appt × appointment_count × ml_spoilage_probability
```
- Outputs: `routing_decision`, `priority_score`, `facility_recommendations[]`
- `actions_required[]` generated from routing outcome + spoilage threshold
- **Why deterministic is correct**: Appointment rescheduling affects patients downstream.
  The formula is transparent: stakeholders can verify priority ranking.

#### 6. insurance_agent — DETERMINISTIC (Loss Calculation + History)

**How it works (code: `tools/insurance_agent.py`)**:
```
product_costs.json → unit_cost, units_per_shipment, disposal_cost_per_unit,
                      downstream_disruption_per_appointment, handling_fee_pct
_compute_loss_breakdown():
  product_loss = unit_cost × units × spoilage_probability
  disposal = disposal_per_unit × units
  handling = (product_loss + disposal) × handling_fee_pct
  disruption = downstream_per_appt × appointment_count
  total = sum + risk_multiplier (CRITICAL: 1.15, HIGH: 1.08, MEDIUM: 1.0)

_aggregate_leg_history() from scored_windows.csv:
  total excursion minutes, max temp deviation, breach count, timeline
```
- `claim_id`: timestamp-based (CLM-YYYYMMDDHHMMSS)
- `next_steps[]`: static list (audit trail, QA sign-off, replacement, submit to carrier)
- **Why deterministic is correct**: Insurance claims are legal documents. Every dollar
  must trace to a formula. LLM-generated loss estimates would be challenged in court.

#### 7. triage_agent — DETERMINISTIC (Sort + Enrichment)

**How it works (code: `tools/triage_agent.py`)**:
```
Input: list of {shipment_id, risk_tier, fused_risk_score, product_id}
Sort: tier_order (CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3) then -fused_risk_score

Optional enrichment (enrich=True):
  scored_windows.csv → filter by shipment_id →
    hours_at_risk = breach_window_count × 0.5
    peak_temp = max(avg_temp_c)
    primary_breach_rule = mode(det_rules_fired)
    product_name from product_profiles

urgency_label: CRITICAL="Immediate", HIGH="Urgent", MEDIUM="Monitor", LOW="Routine"
```
- Output: `priority_list[]` with rank, enrichment data, `recommended_orchestration_order[]`
- **Why deterministic is correct**: Triage ranking must be consistent — if two operators
  see the same shipments, they must get the same priority order.

#### 8. approval_workflow — DETERMINISTIC (State Machine)

**How it works (code: `tools/approval_workflow.py`)**:
```
_execute():
  approval_id = "APR-" + uuid4().hex[:8]
  Store in _PENDING_APPROVALS dict (in-memory)
  Return: status="approval_requested", message, approval_id

get_pending(): return list of pending approvals
decide(approval_id, decision, decided_by):
  Update status to "approved"/"rejected", add decided_by + timestamp
```
- No decision-making — it's a queue/store for human review
- **Why deterministic is correct**: The whole point is human-in-the-loop. The tool
  doesn't decide; it presents the case for a human to decide.

### Summary: Honest Classification

```
GENUINELY AGENTIC (LLM reasoning, novel outputs):
  ┌─────────────────────────────────────────────────────────┐
  │ plan_llm()       → LLM selects tools + constructs inputs│  6 components
  │ reflect_llm()    → LLM self-critiques against GDP/FDA   │  out of 14
  │ revise_llm()     → LLM rewrites plan to fix reflection gaps        │
  │ observe_llm()    → post-execution inspection + re-plan trigger  │
  │ compliance_agent → RAG search + LLM interprets regs     │
  │ route_agent      → LLM picks among safe candidates      │
  └─────────────────────────────────────────────────────────┘

DETERMINISTIC (rule-based, reproducible):
  ┌─────────────────────────────────────────────────────────┐
  │ cold_storage_agent   → weighted scoring formula         │
  │ scheduling_agent     → feasibility + priority formula   │  8 components
  │ insurance_agent      → loss arithmetic from JSON costs  │  out of 14
  │ notification_agent   → dict assembly, no decisions      │
  │ triage_agent         → two-key sort                     │
  │ approval_workflow    → in-memory dict store             │
  │ execute node         → sequential for-loop + deps / failed_tools │
  │ interpret + compile_output → tier parse + JSON assembly │
  └─────────────────────────────────────────────────────────┘
```

**This is a tool-use agent architecture** — the LLM orchestrator decides strategy,
deterministic tools execute with precision. This pattern (ReAct / function-calling
agent) is standard in production agentic systems. The tools don't need to be "smart"
— the orchestrator is the brain.

But we should not overstate it. The system does NOT:
- Discover or compose new tools at runtime
- Learn from past orchestrations to improve future plans
- Dynamically decide cascade enrichment (it's hardcoded per-tool)

These are genuine improvements for future iterations.

### What Would Make This System More Agentic (Prioritized)

| # | Change | Impact | Difficulty | Status |
|---|--------|--------|------------|--------|
| 1 | ~~**Observation loop**~~ | Very High | Medium | **DONE** — `observe_llm()` inspects execution results, triggers re-plan for CRITICAL when tools fail (max 1 iteration) |
| 2 | ~~**LLM-powered revise**~~ | High | Easy | **DONE** — `revise_llm()` sends draft + reflection + context to Groq, rewrites full plan with correct inputs |
| 3 | ~~**Human tool selection**~~ | High | Medium | **DONE** — Approvals page has per-tool toggles, `POST /api/approvals/{id}/execute` + `run_orchestrator_selective()` |
| 4 | ~~**Approval→execution bridge**~~ | High | Medium | **DONE** — Execute button on approved items, WebSocket sync between Agent Activity and Approvals |
| 5 | ~~**Result-aware execute**~~ | Medium | Easy | **DONE** — `execute()` tracks `failed_tools`, `_DEPENDS_ON` map, injects warnings into downstream tools |
| 6 | **Dynamic cascade**: LLM decides what context to pass between tools | Medium | Medium | Open |
| 7 | **cold_storage + LLM**: After scoring, LLM explains facility trade-offs | Medium | Easy | Open |
| 8 | **insurance + LLM narrative**: Keep formula for numbers, add LLM-drafted claim narrative | Medium | Easy | Open |
| 9 | **notification + LLM**: LLM selects stakeholders/channels based on urgency | Medium | Medium | Open |
| 10 | **triage + LLM**: LLM assesses cross-shipment dependencies | Low | Hard | Open |

---

## Further Improvements

| # | Improvement | Impact | Difficulty |
|---|------------|--------|-----------|
| 1 | **Populate compliance vector store** — run `ingest_compliance_docs.py` with PDFs | High | Easy |
| 2 | ~~LLM-powered revise node~~ | ~~High~~ | ~~Medium~~ | **Done** |
| 3 | **LLM-powered notification agent** — Yash's architecture for stakeholder/channel/escalation | High | Medium |
| 4 | **Real-time Supabase listener in backend** — auto-subscribe to window_features changes | High | Medium |
| 5 | **LangSmith tracing** — full observability of LLM calls, latency, token usage | High | Easy |
| 6 | **Dashboard LLM config panel** — UI for `/api/llm/configure` | Medium | Medium |
| 7 | **Real routing API** — FlightAware/OpenSky for live route options | High | Hard |
| 8 | **Webhook notifications** — Twilio/SendGrid for real alert delivery | Medium | Medium |
| 9 | **CI/CD pipeline** — GitHub Actions for testing + deployment | Medium | Medium |
| 10 | **Write risk scores back to Supabase** — `risk_scores` table for downstream consumers | Medium | Easy |
| 11 | **Multi-agent collaboration** — triage agent feeds prioritized list to orchestrator automatically | High | Medium |
| 12 | **Historical trend analysis** — LLM analyzes patterns across shipments for proactive alerts | High | Hard |
| 13 | **Persist approval workflow** — store pending approvals in Supabase, not in-memory | Medium | Easy |
| 14 | **API authentication** — JWT/API key middleware on all endpoints | Critical | Medium |

---

## Verified E2E Test Results (April 14, 2026)

| Test | Result |
|------|--------|
| Supabase connection (all 4 data tables) | 7,411 windows, 6 profiles, 6 costs, 6 facilities |
| Supabase pgvector (compliance_knowledge) | Connected, 417 docs/chunks available for live RAG search |
| Groq LLM agentic orchestration (CRITICAL) | 6 tools, 0 errors, ~11s, LLM reasoning captured |
| Deterministic fallback (CARGO_LLM_ENABLED=0) | 6 tools, 0 errors, ~1.2s |
| **RAG compliance (CRITICAL)** | **vector_search_llm: violation, quarantine, director-level approval, deviation_report=True, 2 violations cited** |
| **RAG compliance (MEDIUM)** | **vector_search_llm: violation, 3 tools executed, 0 errors** |
| **RAG compliance (LOW)** | **0 tools (correct: monitoring only)** |
| Compliance cascade enrichment | product_category, current_temp_c (14.2°C), minutes_outside_range (55), transit_phase, spoilage_probability (0.85), at_risk_value ($100K) — all correctly populated |
| Route agent LLM selection | `P04` CRITICAL reroute → `selection_method=llm`, `temp_class=frozen`, carrier=`Atlas Air Cold Chain` |
| Route agent in orchestrator E2E | CRITICAL `air_handoff` run executed `route_agent` with 0 errors after revise safety net |
| Streaming bridge → ingest endpoint | Local bridge test passed: `stream_listener._forward_record()` → `/api/ingest` returned `200 OK`, tier=`LOW`, score=`0.2640` |
| Insurance downstream_disruption | P04: $57,800 / P01: $33,600 (was $0 before Mukul's fix) |
| Triage enrichment | hours_at_risk, peak_temp, primary_breach_rule populated from scored_windows.csv |
| POST /api/ingest (real-time scoring) | risk_tier=HIGH, score=0.6512, 3 det rules fired |
| GET /api/triage/critical-shipments | 3 enriched shipments ranked correctly |
| Backend API (/api/orchestrator/mode, /api/llm/status, /api/risk/overview) | All 200 OK |
| Module imports (12 modules including tools/helper) | 0 errors |
| Linter checks (12+ files) | 0 errors |
| **Observation loop (CRITICAL)** | **observe_llm detected cold_storage failure + compliance gaps, triggered re-plan (replan_count=1)** |
| **LLM revise (CRITICAL with gaps)** | **revise_llm expanded 5-step draft to 9-step revised plan, adding missing tools** |
| **Result-aware execute** | **9 tools run, failed_tools tracked, notification warned about cold_storage failure** |
| **POST /api/approvals/{id}/execute** | **Approved plan re-executed with full orchestration or human-selected tools** |
| **WebSocket sync (AgentActivity ↔ Approvals)** | **approval_decided + approval_executed events received in real-time** |
| **Post-approval execution skips approval_workflow** | **Selective runner bypasses graph, 0 ghost approvals created, history entry replaced in-place** |
| **Approval card reflects decided status** | **ApprovalResult shows APPROVED badge + operator name when entry is approved** |
| **run_orchestrator_selective bypasses graph** | **Direct interpret→execute→observe→compile, no LLM plan overwrite of human selections** |
| **Plan-first HITL (CRITICAL)** | **Plan-only output: 0 tools executed, awaiting_approval=True, 5 proposed tools, LLM reasoning captured** |
| **Plan-first HITL (MEDIUM)** | **Auto-executed: 2 tools (compliance + notification), no approval gate, no approval_workflow tool** |
| **Tools execute exactly once** | **CRITICAL: tools run only after human approval. No double-execution. approval_workflow removed from tool chain** |
