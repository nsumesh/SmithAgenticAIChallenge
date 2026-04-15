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
L8   FastAPI Backend (22 endpoints)   DONE   Rahul + Mukul (triage endpoints)
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
  interpret → plan(LLM) → reflect(LLM) → [revise] → execute → output
           │
           │  execute() calls tools sequentially with cascade enrichment
           ▼
  8 Agent Tools: compliance → cold_storage → notification → insurance
                 → scheduling → route → triage → approval_workflow
           │
           ▼
  backend/app.py (FastAPI)     → 22 REST endpoints + WebSocket
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
| 2 | **route_agent** | `tools/route_agent.py` | Temp-class-aware routing: looks up product temp class (frozen/refrigerated/CRT) from profiles, selects carrier from `_ROUTE_TABLE` sorted by urgency keywords | Supabase `product_profiles` + local fallback | **Mukul** |
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
| **route_agent** | `product_id, reason, current_leg_id` | `recommended_route, carrier, eta_change_hours, temp_class` |
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
| **revise** | `nodes.py :: revise()` | Deterministic | Keyword scan on GAP notes → inserts missing tools (compliance at pos 0, approval last, others appended). Supports: compliance, notification, insurance, cold_storage, scheduling, approval | `revised_plan, active_plan, plan_revised` |
| **execute** | `nodes.py :: execute()` | Deterministic | Sequential tool invocation with cascade enrichment. Errors per-tool don't abort chain. | `tool_results, execution_errors, cascade_context, approval_id` |
| **fallback** | `nodes.py :: build_fallback()` | Deterministic | Minimal backup: notification_agent + compliance_agent | `fallback_plan` |
| **output** | `nodes.py :: compile_output()` | Deterministic | Assembles final JSON with LLM reasoning, cascade context (full + 200-char summary), confidence score | `final_output, decision_summary, confidence` |

### Conditional Edges

```
reflect ──→ revise          (if "GAP" found in notes AND not already revised)
reflect ──→ execute         (if plan passes all checks)
reflect ──→ output          (if tier is LOW → skip everything)
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

## Backend API Endpoints (22 + WebSocket)

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
| 10 | FastAPI backend (22 endpoints + WebSocket) | DONE |
| 11 | React dashboard (8 pages with Recharts, Mermaid, Tailwind) | DONE |
| 12 | **Agentic orchestration** (Groq LLM plan + reflect nodes, domain prompts) | DONE |
| 13 | **Multi-provider LLM system** (Groq/Ollama/OpenAI/Anthropic with hot-switch) | DONE |
| 14 | **Supabase data pipeline integration** (supabase_client.py, all 5 tables) | DONE |
| 15 | **Karthik changes integration** (stream_listener, simulate_stream, /api/ingest) | DONE |
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
| M2 | Orchestrator: wired product_id to route_agent via _build_tool_input | DONE |
| M3 | Insurance agent: fixed appointment_count from facilities → real downstream_disruption | DONE |
| M4 | Triage agent: _enrich_shipment() from scored_windows.csv + urgency labels + orchestration order | DONE |
| M5 | Backend: triage API endpoints (critical-shipments, rank) + audit log glob fix | DONE |

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
| 8 | **compliance_knowledge table empty** — vector store works but has 0 documents until `ingest_compliance_docs.py` is run | MEDIUM | Open (run ingestion with PDFs in Supabase Storage) |
| 9 | **`shock_count` 99.7% zeros / `door_open_count` 99.8% zeros** in data | LOW | Open (improve data generation) |
| 10 | **Approval workflow is in-memory** — pending approvals lost on server restart | LOW | Open (persist to Supabase) |

---

## Rule-Based vs Agentic Analysis

| Component | Current State | How to Advance |
|-----------|--------------|----------------|
| **Plan node** | **AGENTIC** (Groq LLM reasons + selects tools + constructs inputs) | Done |
| **Reflect node** | **AGENTIC** (Groq LLM critiques plan against compliance) | Done |
| **Compliance agent** | **AGENTIC** (RAG semantic search + Groq LLM interpretation) | Populate vector store with full regulatory PDFs; add edge-case resolver |
| **Revise node** | Rule-based keyword matching on GAP notes | LLM could rewrite the plan directly |
| **Execute node** | Deterministic sequential loop | LLM could decide execution order dynamically |
| **Interpret node** | Rule-based severity classification | LLM could assess compound risks |
| **Route agent** | Rule-based temp-class lookup | Real routing API + LLM reasoning |
| **Cold storage agent** | Rule-based facility scoring | LLM could negotiate with facilities |
| **Insurance agent** | Formula-based loss calculation | LLM could draft claim narratives |
| **Triage agent** | Sort-based ranking | LLM could assess cross-shipment dependencies |
| **Scheduling agent** | Rule-based feasibility + priority matrix | LLM could coordinate multi-facility schedules |
| **Notification agent** | Template-based payloads | LLM-powered stakeholder selection + channel strategy (Yash designed architecture) |
| **Feature engineering** | Static derived features | LLM could identify anomalous feature combinations |
| **Risk fusion** | Fixed alpha-blend formula | LLM could dynamically weight det vs ML |

---

## Further Improvements

| # | Improvement | Impact | Difficulty |
|---|------------|--------|-----------|
| 1 | **Populate compliance vector store** — run `ingest_compliance_docs.py` with PDFs | High | Easy |
| 2 | **LLM-powered revise node** — let LLM rewrite the plan instead of keyword patching | High | Medium |
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
| Supabase pgvector (compliance_knowledge) | Connected, 0 docs (awaiting PDF ingestion) |
| Groq LLM agentic orchestration (CRITICAL) | 6 tools, 0 errors, ~11s, LLM reasoning captured |
| Deterministic fallback (CARGO_LLM_ENABLED=0) | 6 tools, 0 errors, ~1.2s |
| **RAG compliance (CRITICAL)** | **vector_search_llm: violation, quarantine, director-level approval, deviation_report=True, 2 violations cited** |
| **RAG compliance (MEDIUM)** | **vector_search_llm: violation, 3 tools executed, 0 errors** |
| **RAG compliance (LOW)** | **0 tools (correct: monitoring only)** |
| Compliance cascade enrichment | product_category, current_temp_c (14.2°C), minutes_outside_range (55), transit_phase, spoilage_probability (0.85), at_risk_value ($100K) — all correctly populated |
| Route agent temp-class routing | P01→refrigerated, P03→CRT, P04→frozen (correct per profiles) |
| Insurance downstream_disruption | P04: $57,800 / P01: $33,600 (was $0 before Mukul's fix) |
| Triage enrichment | hours_at_risk, peak_temp, primary_breach_rule populated from scored_windows.csv |
| POST /api/ingest (real-time scoring) | risk_tier=HIGH, score=0.6512, 3 det rules fired |
| GET /api/triage/critical-shipments | 3 enriched shipments ranked correctly |
| Backend API (/api/orchestrator/mode, /api/llm/status, /api/risk/overview) | All 200 OK |
| Module imports (12 modules including tools/helper) | 0 errors |
| Linter checks (12+ files) | 0 errors |
