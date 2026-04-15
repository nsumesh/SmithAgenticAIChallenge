# AI Cargo Monitor -- Pharmaceutical Cold-Chain Risk Intelligence

An end-to-end **agentic AI system** that monitors temperature-sensitive pharmaceutical
shipments in real time, predicts spoilage risk with hybrid ML+rules scoring,
orchestrates autonomous mitigation actions through 8 specialized agents, validates
regulatory compliance via RAG-powered LLM interpretation, and maintains full
FDA/GDP audit trails -- all powered by a LangGraph pipeline with a React dashboard.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SUPABASE  (Cloud Data Platform)                   │
│   window_features │ product_profiles │ facilities │ product_costs   │
│   compliance_knowledge (pgvector) │ compliance_docs (Storage)       │
└──────────┬──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 1: DATA PIPELINE                                              │
│  supabase_client.py (paginated fetch + local fallback)               │
│  stream_listener.py (Supabase Realtime → POST /api/ingest)           │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 2: RISK SCORING ENGINE                                        │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────┐  │
│  │ Feature Eng.   │  │ Deterministic    │  │ XGBoost Predictor   │  │
│  │ (14 features)  │  │ Rules (8 rules)  │  │ (Optuna + SHAP)     │  │
│  └────────┬───────┘  └────────┬─────────┘  └──────────┬──────────┘  │
│           └───────────────────┴──────────────┐        │             │
│                                              ▼        │             │
│                                    ┌──────────────────┤             │
│                                    │   Risk Fusion    │◄────────────┘ │
│                                    │  (0.4d + 0.6ml)  │              │
│                                    └────────┬─────────┘              │
└─────────────────────────────────────────────┼────────────────────────┘
                                              │
           ┌──────────────────────────────────┘
           │  risk_input: {risk_tier, fused_score, ml_prob, rules, ...}
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 3: CONTEXT ASSEMBLER                                          │
│  delay_ratio, delay_class, hours_to_breach, facility, product_cost   │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 4: AGENTIC ORCHESTRATION  (LangGraph StateGraph)              │
│                                                                      │
│  interpret → plan(LLM) → reflect(LLM) → [revise(LLM)] → execute    │
│                                                     → observe(LLM)  │
│                                              [replan ←┘] → output   │
│                                                │                     │
│                 ┌──────────────────────────────┘                     │
│                 │  cascade enrichment: each tool's output            │
│                 │  enriches the inputs of downstream tools           │
│                 ▼                                                     │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐           │
│  │compliance│ │cold_store│ │ notify     │ │ schedule   │           │
│  │(RAG+LLM) │ │          │ │            │ │            │           │
│  ├──────────┤ ├──────────┤ ├────────────┤ ├────────────┤           │
│  │insurance │ │  route   │ │  triage    │ │  approval  │           │
│  └──────────┘ └──────────┘ └────────────┘ └────────────┘           │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 5: BACKEND + DASHBOARD                                        │
│  FastAPI (25 endpoints + WebSocket)                                  │
│  React 19 + Vite + Tailwind v4 + Recharts + Mermaid                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# 1. Clone and enter
cd AI_cargo

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env   # then fill in your keys
# Required:  SUPABASE_URL, SUPABASE_KEY
# Required:  GROQ_API_KEY  (for agentic mode + RAG compliance)
# Optional:  OPENAI_API_KEY, ANTHROPIC_API_KEY

# 5. Train the risk model
python3 pipeline.py train

# 6. Start the backend
python3 -m uvicorn backend.app:app --port 8000

# 7. Start the dashboard
cd dashboard && npm install && npm run dev

# Dashboard → http://localhost:5173
# API docs  → http://localhost:8000/docs
```

### LLM Configuration

The system supports 4 LLM providers with automatic fallback:

| Provider | Model | Speed | Env Vars |
|----------|-------|-------|----------|
| **Groq** (default) | `llama-3.3-70b-versatile` | ~1-2s | `GROQ_API_KEY` |
| Ollama | `qwen2.5:7b` | ~5-10s | (local, auto-detected) |
| OpenAI | `gpt-4o-mini` | ~2-3s | `OPENAI_API_KEY` |
| Anthropic | `claude-3-5-haiku-latest` | ~2-3s | `ANTHROPIC_API_KEY` |

```bash
# Priority order (default)
CARGO_LLM_PRIORITY="groq,ollama,openai,anthropic"

# Disable LLM entirely (deterministic-only mode)
CARGO_LLM_ENABLED=0

# Hot-reconfigure at runtime (no restart needed)
curl -X POST http://localhost:8000/api/llm/configure \
  -H "Content-Type: application/json" \
  -d '{"groq_api_key": "gsk_...", "priority": "groq,openai"}'
```

---

## Project Structure

```
AI_cargo/
│
├── pipeline.py                    LangGraph risk-scoring pipeline (train/score)
├── system_prompt.md               Orchestrator agent system prompt
├── requirements.txt               Python dependencies
├── ARCHITECTURE.md                Detailed system architecture (I/O specs per tool)
├── PROGRESS_REPORT.md             Task tracking & team distribution
├── .env                           API keys and configuration
│
├── data/
│   ├── single_table.csv           7,408 telemetry windows (local fallback)
│   ├── product_profiles.json      WHO-aligned temperature thresholds
│   ├── product_costs.json         Per-product cost/insurance data
│   └── facilities.json            Cold-storage facility database
│
├── src/                           Risk scoring engine
│   ├── data_loader.py             Supabase-first loader with local fallback
│   ├── supabase_client.py         Centralized Supabase client (5 tables + write)
│   ├── feature_engineering.py     14 derived features (rolling, lag, deviation)
│   ├── deterministic_engine.py    8 product-aware rules → composite score
│   ├── predictive_model.py        XGBoost + Optuna + SHAP explainability
│   ├── risk_fusion.py             Weighted blend + deterministic veto + NaN handling
│   ├── context_assembler.py       Enriches risk data with delay/breach/facility context
│   └── compliance_logger.py       GDP/FDA JSONL audit records per window
│
├── orchestrator/                  Agentic orchestration (LangGraph)
│   ├── state.py                   OrchestratorState TypedDict (shared graph state)
│   ├── nodes.py                   Deterministic nodes + cascade enrichment
│   ├── llm_nodes.py               Agentic LLM-powered plan + reflect nodes
│   ├── llm_provider.py            Multi-provider LLM (Groq/Ollama/OpenAI/Anthropic)
│   └── graph.py                   StateGraph construction + mode switching
│
├── tools/                         LangChain StructuredTools (8 agents)
│   ├── compliance_agent.py        RAG compliance (pgvector + Groq LLM + audit log)
│   ├── route_agent.py             LLM-assisted safe route selection from certified route options
│   ├── cold_storage_agent.py      Facility lookup with suitability scoring
│   ├── notification_agent.py      Multi-channel stakeholder alerts
│   ├── scheduling_agent.py        Facility reschedule with financial impact
│   ├── insurance_agent.py         Itemized claim preparation with loss breakdown
│   ├── triage_agent.py            Multi-shipment urgency ranking with enrichment
│   ├── approval_workflow.py       Human-in-the-loop approval queue
│   ├── __init__.py                ALL_TOOLS list + TOOL_MAP registry
│   └── helper/                    RAG compliance sub-modules
│       ├── vector_store.py        Supabase pgvector + mock fallback
│       ├── mock_vector_store.py   6 hardcoded FDA/ICH/WHO/GDP regulations
│       ├── embeddings.py          SentenceTransformer (all-MiniLM-L6-v2)
│       ├── llm_interpreter.py     Groq LLM for edge-case compliance
│       ├── document_parser.py     PDF → chunked text (500 words, 50 overlap)
│       ├── ingest_compliance_docs.py  Supabase Storage → vector store pipeline
│       └── mocks.py               MockComplianceAgent for testing
│
├── streaming/                     Real-time data pipeline
│   ├── stream_listener.py         Supabase Realtime → POST /api/ingest
│   └── simulate_stream.py         CSV replay → Supabase for testing
│
├── backend/                       FastAPI REST + WebSocket API
│   ├── app.py                     25 endpoints + WebSocket + LLM config
│   └── models.py                  Pydantic schemas (risk engine ↔ orchestrator)
│
├── dashboard/                     React + Vite + Tailwind + Recharts
│   └── src/components/
│       ├── Overview.jsx           KPI cards, tier pie chart, risky shipments
│       ├── Monitoring.jsx         Live risk feed, alert banners
│       ├── ShipmentList.jsx       Filterable shipment table
│       ├── ShipmentDetail.jsx     Temp + risk timelines, window table
│       ├── AgentActivity.jsx      Orchestrator decisions, tool results, LLM reasoning
│       ├── GraphView.jsx          Mermaid-rendered orchestration + system topology
│       ├── AuditLog.jsx           Compliance records with SHAP features
│       └── Approvals.jsx          Human approval queue (approve/reject)
│
├── artifacts/                     Generated outputs
│   ├── xgb_spoilage.joblib       Trained XGBoost model
│   └── scored_windows.csv        Full scored dataset
│
├── audit_logs/                    Compliance audit trail
│   ├── audit_YYYYMMDD.jsonl      Per-window risk audit records
│   └── compliance_events.jsonl   RAG compliance validation records
│
└── notebooks/
    └── 01_eda_data_quality.ipynb  EDA & data quality report
```

---

## Hybrid Risk Scoring

The system combines two independent scoring layers:

**Deterministic rules** (instant, auditable, 8 product-aware rules):

| Rule | Trigger | Score |
|------|---------|-------|
| `temp_critical_breach` | Outside critical limits | 0.60 |
| `temp_warning_breach` | Outside normal limits | 0.30 |
| `temp_trend` | Slope >1°C/hr toward breach | 0.20 |
| `excursion_duration` | Cumulative min > product tolerance | 0.30 |
| `battery_critical` | Battery < 20% | 0.15 |
| `humidity_alert` | Humidity > threshold | 0.10 |
| `delay_temp_stress` | Delay >120min + near breach | 0.25 |
| `freeze_risk` | Freeze-sensitive + temp ≤0°C | 0.50 |

**XGBoost predictor** (learned, probabilistic):
- 14 engineered features (rolling stats, lag transforms, progress indicators)
- Optuna-tuned hyperparameters (30 trials, PR-AUC objective)
- SHAP values for every prediction (regulatory explainability)
- Shipment-stratified train/val/test split (no temporal leakage)

**Fusion**: `final = 0.4 × deterministic + 0.6 × ML`, with deterministic veto
for critical breaches (det_score > 0.8 cannot be reduced by ML).
NaN handling: missing score defaults to the available one; both NaN → 0.5 (MEDIUM).

| Tier | Score Range | Action |
|------|-------------|--------|
| LOW | 0.0 -- 0.3 | Standard monitoring |
| MEDIUM | 0.3 -- 0.6 | Increased frequency, pre-alert |
| HIGH | 0.6 -- 0.8 | Active intervention, notify ops |
| CRITICAL | 0.8 -- 1.0 | Immediate action, human approval |

---

## Agentic Orchestration

The orchestration agent is a **LangGraph StateGraph** implementing a
**plan-reflect-revise-execute** loop. In **agentic mode**, the LLM decides
which tools to call AND constructs the tool input payloads -- it is not a
template executor.

```
interpret → plan(LLM) → reflect(LLM) → [revise(LLM)] → approval_gate
  MEDIUM:        → execute → observe(LLM) → [replan?] → output (automatic)
  HIGH/CRITICAL: → output (plan-only, awaiting human approval)
  After approval: execute approved tools → observe → output
```

### Orchestration Nodes

| Node | Mode | What it does |
|------|------|-------------|
| **interpret** | Deterministic | Classifies severity, identifies primary issue from rule flags |
| **plan** | **Agentic** (Groq LLM) | LLM analyzes risk, selects tools, constructs inputs with domain reasoning |
| **plan** | Deterministic fallback | Tier-based templates with `_build_tool_input()` |
| **reflect** | **Agentic** (Groq LLM) | LLM critiques plan against GDP/FDA compliance requirements |
| **reflect** | Deterministic fallback | 5-point checklist |
| **revise** | **Agentic** (Groq LLM) | LLM rewrites plan to fix all gaps, deduplicates tools |
| **revise** | Deterministic fallback | Keyword scan on GAP notes, inserts missing tools |
| **approval_gate** | Deterministic | Pauses pipeline for HIGH/CRITICAL; creates approval with proposed tools. MEDIUM auto-continues to execute |
| **execute** | Deterministic | Result-aware cascade execution with dependency tracking (`failed_tools`, `_DEPENDS_ON` map) |
| **observe** | **Agentic** (Groq LLM) | Inspects execution results, triggers re-plan for CRITICAL failures (max 1 loop) |
| **fallback** | Deterministic | Minimal backup plan if execution had errors |
| **output** | Deterministic | Assembles final JSON with LLM reasoning, observation, and re-plan count |

### Cascade Enrichment

During execution, each tool's output enriches inputs to downstream tools:

| Source Tool | Feeds Into | What Flows |
|-------------|-----------|------------|
| `cold_storage_agent` | `notification_agent` | facility name, advance notice, temp range |
| `cold_storage_agent` | `scheduling_agent` | facility, advance notice, temp range |
| `compliance_agent` | `insurance_agent` | log_id as supporting evidence |
| Product cost data | `insurance_agent` | estimated_loss_usd |
| All tools | `approval_workflow` | consolidated action summaries |

### Human-in-the-Loop Approval Flow

The system implements a **plan-first** HITL pattern — tools only execute after human review:

1. **Orchestration triggered** — LLM generates plan, reflects, revises (full agentic pipeline)
2. **Approval gate** — HIGH/CRITICAL events pause here. The plan and proposed tools are stored.
   MEDIUM events skip the gate and auto-execute.
3. **Human reviews plan** — Dashboard shows the LLM's proposed tools and reasoning
4. **Operator decides** — Approve (with optional tool selection) or reject
5. **Post-approval execution** — `run_orchestrator_selective()` executes only the approved
   tools. Tools run exactly once — never before approval.
6. **Observe + Output** — LLM inspects results, history updated in-place via WebSocket

### RAG Compliance Agent

The compliance agent uses **Retrieval-Augmented Generation** for regulatory validation:

1. **Audit log** -- immutable JSONL append (always succeeds, GDP-compliant)
2. **Semantic search** -- query Supabase pgvector (`compliance_knowledge` table) using
   sentence-transformer embeddings (`all-MiniLM-L6-v2`, 384 dimensions)
3. **LLM interpretation** -- Groq `llama-3.3-70b-versatile` interprets retrieved
   regulations against shipment context → compliance decision, violations, disposition
4. **Fallback chain** -- mock regulations if vector store empty → deterministic
   decision if LLM unavailable → audit-only if both fail

### Agentic vs Deterministic Mode

| Feature | Agentic | Deterministic |
|---------|---------|---------------|
| Plan generation | LLM reasons about situation | Tier templates |
| Tool inputs | LLM constructs from risk data | `_build_tool_input()` |
| Reflection | LLM compliance critique | Checklist matching |
| Compliance | RAG search + LLM interpretation | Append-only audit log |
| Latency | ~10-15s (Groq) | <1s |
| Provider | Groq / Ollama / OpenAI / Anthropic | None needed |

---

## Supabase Integration

All data access goes through `src/supabase_client.py` with automatic local fallback:

| Table | Rows | Used By | Fallback |
|-------|------|---------|----------|
| `window_features` | 7,411 | data_loader, ingest endpoint | `data/single_table.csv` |
| `product_profiles` | 6 | deterministic engine, all agents | `data/product_profiles.json` |
| `product_costs` | 6 | insurance, scheduling agents | `data/product_costs.json` |
| `facilities` | 6 | cold_storage, insurance, scheduling | `data/facilities.json` |
| `compliance_knowledge` | 417 | RAG compliance agent (pgvector) | regulations from documents |
| `compliance_docs` | (Storage bucket) | PDF ingestion pipeline | (none) |

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/risk/overview` | GET | Tier distribution, KPIs, top risky shipments |
| `/api/shipments` | GET | All shipments, filterable by `risk_tier` |
| `/api/shipments/{id}/windows` | GET | All windows for a shipment |
| `/api/windows` | GET | Windows, filterable by tier/product, paginated |
| `/api/windows/{window_id}` | GET | Single window detail |
| `/api/risk/score-window/{id}` | GET | Risk engine output for orchestrator |
| `/api/ingest` | POST | Real-time single-window scoring (from stream) |
| `/api/orchestrator/run/{id}` | POST | Run orchestration agent on a window |
| `/api/orchestrator/run-batch` | POST | Orchestrate multiple windows |
| `/api/orchestrator/history` | GET | Recent orchestrator decisions |
| `/api/orchestrator/mode` | GET | Current mode (agentic/deterministic) |
| `/api/tools/{name}/execute` | POST | Execute any agent tool directly |
| `/api/triage/critical-shipments` | GET | Auto-triage: pull worst shipments, rank |
| `/api/triage/rank` | POST | Rank caller-supplied shipments |
| `/api/graph/mermaid` | GET | Orchestrator graph as Mermaid string |
| `/api/graph/topology` | GET | Full 5-layer system topology JSON |
| `/api/audit-logs` | GET | Compliance audit records |
| `/api/approvals/pending` | GET | Pending human approval requests |
| `/api/approvals/all` | GET | All approvals (pending + approved + rejected) |
| `/api/approvals/{id}/decide` | POST | Approve or reject an action |
| `/api/approvals/{id}/execute` | POST | Execute approved plan (skips approval_workflow to prevent ghost approvals) |
| `/api/orchestrator/history` | DELETE | Clear in-memory orchestration history |
| `/api/llm/status` | GET | Active LLM provider, available providers |
| `/api/llm/configure` | POST | Hot-configure API keys, priority, models |
| `/ws/events` | WebSocket | Real-time event stream |

---

## Data Quality Findings

| Finding | Impact | Status |
|---------|--------|--------|
| `shock_count` 99.7% zeros | Low ML signal | Flagged for data gen update |
| `door_open_count` 99.8% zeros | Low ML signal | Flagged for data gen update |
| `minutes_outside_range > 0` implies target=1 | Leaky feature | Used in det only; lag-transformed for ML |
| P03 zero spoilage events | Under-modeled | Add CRT excursion scenarios |
| P06: 37.8% spoilage rate | Dominates positives | Handled via stratified split |
| 17% class imbalance | ML bias | scale_pos_weight=4.9 in XGBoost |

## Model Performance

| Metric | Validation | Test |
|--------|-----------|------|
| PR-AUC | 0.9987 | 0.5822 |
| ROC-AUC | 0.9997 | 0.9446 |
| F1 | 0.9742 | 0.4118 |

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Risk Engine** | Python, pandas, scikit-learn, XGBoost, SHAP, Optuna |
| **Orchestration** | LangGraph, LangChain Core |
| **LLM Providers** | Groq (llama-3.3-70b), Ollama (qwen2.5:7b), OpenAI, Anthropic |
| **RAG Compliance** | Supabase pgvector, sentence-transformers, Groq LLM |
| **Data Platform** | Supabase (PostgreSQL, Realtime, Storage) |
| **Backend** | FastAPI, Pydantic, uvicorn |
| **Frontend** | React 19, Vite, Tailwind CSS v4, Recharts, Mermaid |
| **Compliance** | JSONL audit logs, SHAP explainability, human-in-the-loop |



