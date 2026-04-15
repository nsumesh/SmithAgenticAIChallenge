# AI Cargo Monitoring — Presentation Content (Slide-by-Slide)

> Use this as the source for building your PowerPoint. Each section = 1 slide (or 2 if dense).
> Speaker notes are under each slide.

---

## SLIDE 1 — Title

**AI Cargo Monitor**
*Agentic AI for Pharmaceutical Cold-Chain Risk Intelligence*

- Team: Rahul · Karthik · Mukul · Yash · Nikhil
- Course / Date: [Fill in]

**Speaker notes**: We built an end-to-end agentic AI system that monitors temperature-sensitive pharmaceutical shipments, predicts spoilage risk, orchestrates autonomous mitigation actions, and validates FDA/GDP compliance — with human-in-the-loop control.

---

## SLIDE 2 — Problem Statement

**The $35B problem: Pharmaceutical spoilage in cold-chain logistics**

- 25% of vaccines reach destination degraded due to cold-chain failures (WHO)
- $35 billion lost annually to temperature excursions in pharma logistics
- FDA 21 CFR Part 211, WHO TRS 961, EU GDP — require documented, traceable decisions
- Manual monitoring cannot scale: 7,400+ telemetry windows per shipment batch
- Delayed response = product destruction, patient harm, regulatory penalties

**Key question**: Can an AI agent autonomously detect risks, plan mitigation, validate compliance, and execute actions — while keeping a human in the loop for irreversible decisions?

**Speaker notes**: Temperature excursions during pharmaceutical transport are a massive real-world problem. A single shipment of Plasma Derivative (P06) can be worth $100K+. If it sits outside 2-8°C for too long, the entire batch must be destroyed. Currently this monitoring is manual and reactive. We built a system that makes it autonomous and proactive.

---

## SLIDE 3 — Solution Overview (Idea)

**An agentic AI system with 5 layers**

| Layer | What it does |
|-------|-------------|
| **Data Pipeline** | Supabase cloud → paginated fetch → local CSV fallback |
| **Risk Scoring** | 8 deterministic rules + XGBoost ML → fused 4-tier risk |
| **Context Assembly** | Enriches risk data: delay class, hours to breach, facility, costs |
| **Agentic Orchestration** | LLM plans → reflects → revises → human approves → executes |
| **Dashboard** | React real-time ops dashboard with approval queue |

**What makes it agentic?**
- The LLM decides *which* tools to call, *what* inputs to construct, and *why*
- It self-critiques (reflect), self-corrects (revise), and self-evaluates (observe)
- Human controls irreversible actions via plan-first approval gate
- 8 specialized tools execute autonomously with cascade context passing

**Speaker notes**: This is not a chatbot or a simple ML model. It's a multi-agent system where an LLM orchestrator reasons about risk events, builds action plans, validates them against regulatory requirements, and coordinates 8 specialized tools. The human only steps in for high-stakes decisions.

---

## SLIDE 4 — Architecture Diagram

*[Insert the system architecture diagram from GraphView — the 5-layer Mermaid diagram]*

```
SUPABASE (Cloud)
    ↓
LAYER 1: Data Pipeline (supabase_client.py + stream_listener.py)
    ↓
LAYER 2: Risk Scoring (Feature Eng → Det. Rules → XGBoost → Fusion)
    ↓
LAYER 3: Context Assembler (delay_ratio, hours_to_breach, facility data)
    ↓
LAYER 4: Agentic Orchestration (LangGraph: plan → reflect → revise → gate → execute → observe)
    ↓
LAYER 5: FastAPI Backend (25 endpoints + WebSocket) → React Dashboard (8 pages)
```

**Speaker notes**: Data flows top to bottom. Every layer has fallbacks (Supabase fails → local CSV, LLM fails → deterministic rules). The agentic orchestration layer is the brain — it uses the Groq LLM to reason about each risk event and decide what to do.

---

## SLIDE 5 — Data Pipeline (Layer 1)

**From IoT sensors to scored risk windows**

| Data Source | Rows | Purpose |
|------------|------|---------|
| `window_features` | 7,411 | 25-min telemetry aggregation windows |
| `product_profiles` | 6 | WHO-aligned temp thresholds per product |
| `product_costs` | 6 | Unit costs, disposal, handling fees |
| `facilities` | 6 | Cold-storage sites with certifications |
| `compliance_knowledge` | 417 | Regulatory doc chunks (pgvector embeddings) |

**Real-time path**: `stream_listener.py` subscribes to Supabase Realtime → forwards new rows to `POST /api/ingest` → single-window scoring + orchestration in <15 seconds.

**Resilience**: Every data source has a local JSON/CSV fallback. If Supabase is down, the system continues operating on cached data.

**Speaker notes**: Karthik built the data generation and Supabase integration. We have 6 pharmaceutical products (vaccines, insulin, plasma, monoclonal antibodies, gene therapy, whole blood) each with WHO-aligned temperature thresholds. The 7,411 windows represent real-world-like telemetry data.

---

## SLIDE 6 — Hybrid Risk Scoring (Layer 2)

**Two independent scoring systems, fused for reliability**

**Deterministic Rules (8 product-aware rules)**:
| Rule | Trigger | Score |
|------|---------|-------|
| `temp_critical_breach` | Outside critical limits | 0.60 |
| `freeze_risk` | Freeze-sensitive + temp ≤ 0°C | 0.50 |
| `excursion_duration` | Cumulative min > tolerance | 0.30 |
| `temp_warning_breach` | Outside normal limits | 0.30 |
| `delay_temp_stress` | Delay >120min + near breach | 0.25 |
| `temp_trend` | Slope >1°C/hr toward breach | 0.20 |
| `battery_critical` | Battery < 20% | 0.15 |
| `humidity_alert` | Humidity > threshold | 0.10 |

**XGBoost Predictor**: 14 engineered features, Optuna-tuned (30 trials), SHAP explainability

**Fusion Formula**: `final = 0.4 × deterministic + 0.6 × ML`
- Deterministic veto: `det_score > 0.8` cannot be reduced by ML
- NaN handling: missing → fallback to available score; both NaN → 0.5 (MEDIUM)

| Tier | Range | Response |
|------|-------|----------|
| CRITICAL | 0.8-1.0 | Immediate human-approved intervention |
| HIGH | 0.6-0.8 | Active intervention, human approval |
| MEDIUM | 0.3-0.6 | Auto-execute (compliance + notification) |
| LOW | 0.0-0.3 | Monitoring only |

**Speaker notes**: The hybrid approach gives us both speed (rules fire instantly) and nuance (ML captures complex patterns). The veto mechanism ensures truly dangerous situations are never downgraded by the ML model. SHAP values make every prediction explainable for regulators.

---

## SLIDE 7 — Agentic Orchestration (Layer 4) — The Core Innovation

**Plan-First Human-in-the-Loop Architecture**

```
interpret → plan(LLM) → reflect(LLM) → revise(LLM) → APPROVAL GATE
                                                          │
                                           ┌──────────────┴──────────────┐
                                           ▼                             ▼
                                      LOW / MEDIUM                 HIGH / CRITICAL
                                   (auto-execute)              (plan-only → human)
                                   execute → observe                    │
                                      → output               Human reviews plan
                                                              Approves + selects tools
                                                                        │
                                                              execute → observe → output
```

**What each node does**:
| Node | LLM? | Purpose |
|------|------|---------|
| **Interpret** | No | Parse risk tier, identify primary issue |
| **Plan** | **Yes** (Groq) | LLM selects tools + constructs inputs with domain reasoning |
| **Reflect** | **Yes** (Groq) | LLM self-critiques plan against GDP/FDA requirements |
| **Revise** | **Yes** (Groq) | LLM rewrites plan to fix all identified gaps |
| **Approval Gate** | No | HIGH/CRITICAL → pause for human; MEDIUM → auto-execute |
| **Execute** | No | Run tools sequentially with cascade enrichment |
| **Observe** | **Yes** (Groq) | Post-execution: LLM checks results, can trigger re-plan |

**Key design decision**: Tools execute **exactly once** — after human approval for HIGH/CRITICAL, immediately for MEDIUM/LOW. No double execution.

**Speaker notes**: This is the heart of the system. The LLM isn't just executing templates — it genuinely reasons about what to do. For a CRITICAL plasma shipment at 14°C (should be 2-8°C), the LLM might decide: "I need compliance_agent to check WHO TRS 961, cold_storage_agent to find an alternative facility near ORD, insurance_agent because spoilage probability is 85%, and notification_agent to alert the facility." Then the reflect node catches: "You missed scheduling_agent — the receiving facility needs to reschedule appointments." Revise adds it. Only then does the plan go to the human operator.

---

## SLIDE 8 — The 8 Agent Tools

**2 agentic (LLM-powered) + 6 deterministic (auditable formulas)**

| # | Agent | Intelligence | Key Output |
|---|-------|-------------|------------|
| 1 | **Compliance** | **RAG + LLM** | Regulatory violations, product disposition, citations |
| 2 | **Route** | **LLM + Rules** | Temperature-safe carrier selection with rationale |
| 3 | Cold Storage | Weighted scoring | Best backup facility with suitability score |
| 4 | Notification | Payload assembly | Multi-channel alert with cascade data |
| 5 | Scheduling | Feasibility matrix | Facility reschedule + financial impact |
| 6 | Insurance | Loss formula | Itemized claim breakdown ($product + disposal + handling) |
| 7 | Triage | Priority sort | Multi-shipment urgency ranking |
| 8 | Approval | State machine | Human review queue |

**Why deterministic tools are intentional**: In pharmaceutical cold-chain, regulators require **auditable, reproducible** decisions. An LLM hallucinating a $39K insurance claim would be challenged in court. Facility scoring must produce identical outputs for identical inputs. The LLM orchestrator is the brain; deterministic tools are the precise hands.

**Cascade enrichment**: Each tool's output feeds downstream tools:
- compliance result → insurance gets `log_id` as evidence
- cold_storage result → notification gets facility name, scheduling gets advance notice
- product_cost data → insurance calculates `estimated_loss_usd`

**Speaker notes**: The cascade enrichment is what makes this a connected system, not just 8 independent tools. When cold_storage_agent identifies "ColdVault Boston" as the backup facility, notification_agent automatically includes that in the alert message, and scheduling_agent uses the facility's advance notice requirement to check feasibility.

---

## SLIDE 9 — RAG Compliance Agent (Deep Dive)

**Retrieval-Augmented Generation for regulatory validation**

```
Shipment Context → Embedding (all-MiniLM-L6-v2, 384 dim)
    → Supabase pgvector search (417 regulatory chunks)
    → Top-K relevant regulations retrieved
    → Groq LLM (llama-3.3-70b) interprets regulations
    → Output: compliance_status, violations[], disposition, citations[]
```

**Regulatory sources indexed**: WHO TRS 961 Annex 9, EU GDP Guidelines, FDA 21 CFR Part 11, ICH Q9, PIC/S GDP, IATA Vaccine Guidelines

**3-tier fallback chain**:
1. Live pgvector semantic search + LLM interpretation
2. Brute-force cosine similarity + LLM interpretation
3. Mock regulations (6 hardcoded) + deterministic ruling

**Always writes**: Immutable JSONL audit log (GDP-compliant) regardless of which tier runs

**Speaker notes**: Yash built the RAG pipeline. The key insight is that compliance decisions in pharma require citing specific regulations. The LLM doesn't just say "violation" — it cites "WHO TRS 961 Annex 9 Section 4.2: temperature excursions exceeding 15 minutes require documented investigation." This is the difference between an AI recommendation and a regulation-backed decision.

---

## SLIDE 10 — Methodology

**Development approach & engineering decisions**

| Decision | Choice | Why |
|----------|--------|-----|
| **Scoring** | Hybrid (rules + ML) | Rules for speed/auditability, ML for nuance |
| **Orchestration** | LangGraph StateGraph | Stateful graph with conditional edges, not a linear chain |
| **LLM Pattern** | Tool-use agent (ReAct) | LLM reasons about tools, not just classifies |
| **HITL Pattern** | Plan-first | LLM plans, human approves, then tools execute once |
| **Compliance** | RAG over pgvector | Real regulatory documents, not hardcoded rules |
| **Fallback** | Every layer has one | Supabase → CSV, LLM → deterministic, RAG → mock regs |
| **Deterministic tools** | Intentional | Regulatory auditability trumps AI flexibility |
| **Multi-provider LLM** | Priority chain | Groq → Ollama → OpenAI → Anthropic, hot-switchable |

**ML methodology**:
- Shipment-stratified train/val/test split (no temporal leakage)
- Optuna hyperparameter tuning (30 trials, PR-AUC objective)
- `scale_pos_weight=4.9` for 17% class imbalance
- SHAP values for every prediction (regulatory explainability)

**Speaker notes**: Every design choice was intentional. We chose LangGraph over simple function chaining because we needed conditional edges (reflect → revise only if gaps found, approval_gate → execute only for MEDIUM). We chose Groq because it gives us 70B-parameter quality at 1-2 second latency. We chose deterministic tools where regulators demand reproducibility.

---

## SLIDE 11 — Exact Running Order (Workflow)

**What happens when a CRITICAL risk event is detected**

```
Step 1: DATA IN
  Supabase window_features row → supabase_client.py fetches data
  
Step 2: RISK SCORING (pipeline.py)
  feature_engineering.py → 14 derived features (MKT, slope, breach duration)
  deterministic_engine.py → 8 rules fire → det_score = 0.85
  predictive_model.py → XGBoost predicts → ml_probability = 0.92
  risk_fusion.py → fused_score = 0.4(0.85) + 0.6(0.92) = 0.892 → CRITICAL
  compliance_logger.py → audit_logs/audit_20260415.jsonl written
  
Step 3: CONTEXT ASSEMBLY
  context_assembler.py → delay_ratio, delay_class="critical", hours_to_breach=1.8
  
Step 4: ORCHESTRATION (LangGraph)
  4a. interpret_risk() → severity=critical, urgency=immediate
  4b. plan_llm() → Groq LLM generates 5-tool plan + reasoning  (~2s)
  4c. reflect_llm() → Groq LLM finds 1 GAP: missing insurance  (~1.5s)
  4d. revise_llm() → Groq LLM adds insurance_agent, rewrites plan  (~2s)
  4e. approval_gate() → CRITICAL → creates approval APR-XXXX, STOPS
  
Step 5: HUMAN REVIEW (Dashboard)
  Agent Activity shows: plan, reflection, revision, proposed tools
  Approvals tab shows: pending approval with tool toggles
  Operator approves, selects: compliance + cold_storage + notification + insurance
  
Step 6: POST-APPROVAL EXECUTION
  run_orchestrator_selective() → bypasses LangGraph, runs 4 tools:
    6a. compliance_agent → RAG search → violation, quarantine, 2 regs cited  (~3s)
    6b. cold_storage_agent → scores 6 facilities → "ColdVault Boston" (0.82)
    6c. notification_agent → builds alert with facility name + ETA
    6d. insurance_agent → $39,628 claim (product $33K + disposal $3K + handling $2K)
  
Step 7: OBSERVATION
  observe_llm() → Groq LLM reviews results → "adequate, no re-plan needed"
  
Step 8: OUTPUT
  compile_output() → final JSON with all results, confidence=0.85
  WebSocket broadcasts to dashboard → history updated in-place
  
Total: ~12-15 seconds (agentic) or <1 second (deterministic fallback)
```

**Speaker notes**: Walk through this step by step. The key moment is Step 4e — the approval gate. This is where we pause and let the human decide. The LLM has already done all the thinking (plan, reflect, revise), but no tools have fired yet. The human sees the LLM's reasoning and proposed tools, and can add or remove tools before clicking Execute.

---

## SLIDE 12 — MEDIUM Tier (Auto-Execute Flow)

**For MEDIUM risk: fully automatic, no human needed**

```
Risk detected → plan(LLM) → reflect(LLM) → [revise if gaps]
  → approval_gate → MEDIUM: auto-continue
  → execute: compliance_agent + notification_agent (2 tools)
  → observe(LLM) → output
  
Total: ~8 seconds | No human intervention
```

**Design principle**: Only interrupt humans for consequential decisions. MEDIUM events need monitoring and documentation, but don't require facility rerouting or insurance claims.

---

## SLIDE 13 — Delivery (Dashboard)

*[Insert dashboard screenshots]*

**8 interactive pages**:

| Page | What it shows |
|------|--------------|
| **Overview** | KPI cards, tier distribution pie chart, top risky shipments |
| **Monitoring** | Live risk feed with alert banners, real-time scoring |
| **Shipments** | Filterable shipment table with risk tier badges |
| **Shipment Detail** | Temperature + risk timelines, individual window table |
| **Agent Activity** | Full orchestration history: plan → reflect → revise → execute → observe |
| **System Graph** | 3-tab Mermaid diagrams: architecture, data flow, orchestration |
| **Audit Log** | Compliance records with SHAP feature importance |
| **Approvals** | Human approval queue: pending → approved → tool selection → executed |

**Real-time features**:
- WebSocket connection for live orchestration events
- Pipeline step visualizer (shows which nodes ran, which are waiting)
- Post-approval execution replaces history entry in-place
- Proposed tools displayed with LLM reasoning for informed approval

**Tech**: React 19 + Vite + Tailwind CSS v4 + Recharts + Mermaid

---

## SLIDE 14 — Human-in-the-Loop Approval Flow (Demo-Ready)

**Step-by-step walkthrough for live demo**:

1. Navigate to **Agent Activity** → Click "Run" on a CRITICAL window
2. See: Pipeline stops at "Approval Gate" (violet badge)
3. Expand card: LLM reasoning, draft plan, reflection notes, revised plan all visible
4. Banner shows: "Plan Ready — Awaiting Approval"
5. Navigate to **Approvals** → See pending approval with window_id + container_id
6. Review proposed tools, toggle any off
7. Click **Approve** → Tools pre-selected from LLM's recommendations
8. Click **Execute** → Watch Agent Activity update in real-time via WebSocket
9. Pipeline now shows: Plan → Reflect → Revise → **Approved** → Execute → Observe → Output

---

## SLIDE 15 — Technology Stack

| Category | Technologies |
|----------|-------------|
| **Language** | Python 3.11, JavaScript (React) |
| **Risk Scoring** | pandas, scikit-learn, XGBoost, SHAP, Optuna |
| **Orchestration** | LangGraph, LangChain Core |
| **LLM** | Groq (llama-3.3-70b-versatile) — primary |
| | Ollama (qwen2.5:7b) — local fallback |
| | OpenAI, Anthropic — configurable slots |
| **RAG** | Supabase pgvector, sentence-transformers (all-MiniLM-L6-v2) |
| **Data** | Supabase (PostgreSQL + Realtime + Storage), local CSV/JSON |
| **Backend** | FastAPI, Pydantic, uvicorn, WebSocket |
| **Frontend** | React 19, Vite, Tailwind CSS v4, Recharts, Mermaid.js |
| **Compliance** | JSONL audit logs, SHAP explainability, GDP/FDA-aligned |

---

## SLIDE 16 — Team Contributions

| Member | Layers | Key Deliverables |
|--------|--------|-----------------|
| **Rahul** | L2, L4, L5, L8, L9 | Risk engine, agentic orchestration (plan/reflect/revise/observe), multi-provider LLM, FastAPI backend (25 endpoints), React dashboard (8 pages), all integration + E2E tests |
| **Karthik** | L1 | Synthetic data generator, Supabase table setup, stream simulator, Realtime listener |
| **Mukul** | L3 | Route agent (LLM + rules), insurance agent (loss calculation), triage agent (enrichment), triage API endpoints |
| **Yash** | L7 | RAG compliance system: pgvector integration, embeddings, PDF parser, LLM interpreter, mock fallbacks, ingestion pipeline |
| **Nikhil** | L6 | Context assembler, cascade enrichment system, enriched facilities + product costs data |

---

## SLIDE 17 — Challenges, Fixes & Workarounds

| Challenge | What went wrong | How we fixed it |
|-----------|----------------|-----------------|
| **Double tool execution** | Tools ran before AND after approval | Plan-first HITL: approval_gate pauses before execute |
| **Approval was a rubber stamp** | Human approved after tools already fired | Tools now execute only after human review |
| **Ghost approvals** | Post-approval execution re-created approval_workflow | Removed approval_workflow from tool chain; selective runner bypasses graph |
| **RAG async deadlock** | sentence-transformers + Groq in same event loop | Fixed with sync wrapper + thread pool executor |
| **Revise was keyword-matching** | `str.find("compliance")` for gap detection | Replaced with LLM-powered revise (Groq rewrites full plan) |
| **Execute was fire-and-forget** | Failed tools silently swallowed | Added `failed_tools` tracking + `_DEPENDS_ON` dependency map |
| **Cascade data lost** | Downstream tools missed upstream results | `_enrich_tool_input()` passes results through cascade_ctx |
| **WebSocket path mismatch** | Frontend connected to `/ws`, backend served `/ws/events` | Aligned paths in useWebSocket hook + Vite proxy |
| **ML overfitting** | PR-AUC: 0.998 val → 0.582 test | Shipment-stratified split, `scale_pos_weight`, feature analysis |
| **NaN in fusion** | `0.4×NaN + 0.6×ML = NaN` | Added explicit NaN handling: fallback to available score; both NaN → 0.5 |

**Speaker notes**: Every system has bugs. What matters is how you find and fix them. The double-execution bug was the most architecturally significant — it required rethinking the entire HITL pattern from "execute-then-approve" to "plan-then-approve-then-execute."

---

## SLIDE 18 — What Is and Isn't Agentic (Honest Assessment)

**6 out of 14 components are genuinely agentic:**

```
AGENTIC (LLM reasoning, novel outputs):
  ├── plan_llm()        → LLM selects tools + constructs inputs
  ├── reflect_llm()     → LLM self-critiques against GDP/FDA
  ├── revise_llm()      → LLM rewrites plan to fix gaps
  ├── observe_llm()     → LLM inspects results, triggers re-plan
  ├── compliance_agent  → RAG search + LLM interprets regulations
  └── route_agent       → LLM evaluates carrier trade-offs

DETERMINISTIC (rule-based, reproducible):
  ├── cold_storage_agent    → weighted scoring formula
  ├── scheduling_agent      → feasibility + priority matrix
  ├── insurance_agent       → loss arithmetic from cost tables
  ├── notification_agent    → payload assembly
  ├── triage_agent          → two-key sort
  ├── approval_workflow     → in-memory state machine
  ├── execute node          → sequential for-loop with deps
  └── interpret + output    → tier parse + JSON assembly
```

**Architecture pattern**: This is a **tool-use agent** (ReAct pattern). The LLM orchestrator is the brain; deterministic tools are the precise hands. This is the standard pattern in production agentic systems.

---

## SLIDE 19 — Model Performance & Data Quality

| Metric | Validation | Test |
|--------|-----------|------|
| PR-AUC | 0.9987 | 0.5822 |
| ROC-AUC | 0.9997 | 0.9446 |
| F1 | 0.9742 | 0.4118 |

**Acknowledged data issues**:
- `shock_count` 99.7% zeros, `door_open_count` 99.8% zeros → low ML signal
- P03 (CRT product): zero spoilage events → under-modeled
- P06 (plasma derivative): 37.8% spoilage rate → dominates positives
- `minutes_outside_range > 0` strongly implies `target=1` → used in det. rules only

**Mitigation**: Shipment-stratified splits, scale_pos_weight=4.9, deterministic veto override ensures critical breaches are never downgraded by ML overconfidence.

---

## SLIDE 20 — Future Improvements

| Priority | Improvement | Impact |
|----------|------------|--------|
| 1 | **API authentication** (JWT/API key) | Critical for production |
| 2 | **LangSmith tracing** for LLM observability | High — token usage, latency tracking |
| 3 | **Dynamic cascade** — LLM decides what context to pass | High — more agentic |
| 4 | **LLM-powered notification** — stakeholder/channel selection | High — Yash's architecture |
| 5 | **Real routing API** (FlightAware/OpenSky) | High — live route options |
| 6 | **Persist approvals to Supabase** | Medium — survive restarts |
| 7 | **cold_storage + LLM** explanation of facility trade-offs | Medium |
| 8 | **Historical trend analysis** — LLM analyzes patterns proactively | High |
| 9 | **Multi-agent collaboration** — triage feeds orchestrator automatically | High |
| 10 | **CI/CD pipeline** (GitHub Actions) | Medium |

---

## SLIDE 21 — Key Metrics & Numbers

| Metric | Value |
|--------|-------|
| Telemetry windows scored | 7,411 |
| Products monitored | 6 (vaccines, insulin, plasma, mAb, gene therapy, blood) |
| Cold-storage facilities | 6 |
| Regulatory documents indexed | 417 chunks (pgvector) |
| Agent tools | 8 (2 LLM-powered, 6 deterministic) |
| API endpoints | 25 + WebSocket |
| Dashboard pages | 8 |
| LLM providers supported | 4 (Groq, Ollama, OpenAI, Anthropic) |
| Agentic orchestration latency | ~12-15 seconds (Groq) |
| Deterministic fallback latency | < 1 second |
| E2E tests passed | 30+ verified scenarios |
| Files in codebase | 40+ Python/JS modules |

---

## SLIDE 22 — Live Demo Flow

**Suggested demo script (3-5 minutes)**:

1. **Overview page**: Show tier distribution, KPIs, top risky shipments
2. **Shipment Detail**: Click a CRITICAL shipment → temp timeline + risk score
3. **Agent Activity**: Run orchestration on the CRITICAL window
   - Watch pipeline steps light up: Interpret → Plan → Reflect → Revise → Approval Gate
   - Show the LLM reasoning, proposed tools
4. **Approvals**: Show the pending approval, toggle tools, approve + execute
5. **Agent Activity**: See entry update with tool results, observation
6. **System Graph**: Show the full 5-layer architecture diagram
7. **Audit Log**: Show compliance records with SHAP features

---

## SLIDE 23 — References

| Reference | Use in project |
|-----------|---------------|
| WHO TRS 961 Annex 9 — Model guidance for storage and transport | Temperature thresholds, excursion handling rules |
| FDA 21 CFR Part 11 — Electronic records and signatures | Audit log design, immutable JSONL records |
| EU GDP Guidelines (2013/C 343/01) | Good Distribution Practice compliance checks |
| ICH Q9 — Quality Risk Management | Risk tier methodology, MKT calculation |
| PIC/S GDP Guide for Medicinal Products | Compliance agent regulatory knowledge base |
| IATA Guidelines for Vaccine Logistics | Cold-chain transport carrier requirements |
| LangGraph Documentation | StateGraph with conditional edges, state management |
| LangChain StructuredTool API | Tool schema design, Pydantic input validation |
| XGBoost: A Scalable Tree Boosting System (Chen & Guestrin, 2016) | Predictive model |
| SHAP: A Unified Approach to Interpreting Model Predictions (Lundberg & Lee, 2017) | Feature explainability for regulatory compliance |
| Optuna: A Hyperparameter Optimization Framework (Akiba et al., 2019) | XGBoost hyperparameter tuning |
| Supabase Documentation — pgvector, Realtime, Storage | Data platform, vector search, real-time streaming |
| ReAct: Synergizing Reasoning and Acting in LLMs (Yao et al., 2023) | Tool-use agent pattern for orchestration |
| Sentence-Transformers (Reimers & Gurevych, 2019) | all-MiniLM-L6-v2 for compliance RAG embeddings |

---

## APPENDIX — Glossary

| Term | Meaning |
|------|---------|
| **MKT** | Mean Kinetic Temperature — weighted average accounting for thermal stress |
| **GDP** | Good Distribution Practice — EU pharmaceutical distribution standard |
| **HITL** | Human-in-the-Loop — human review before irreversible actions |
| **RAG** | Retrieval-Augmented Generation — LLM + document search |
| **ReAct** | Reason + Act — LLM pattern for tool-use agents |
| **Cascade Enrichment** | Each tool's output feeds into downstream tools' inputs |
| **pgvector** | PostgreSQL extension for vector similarity search |
| **SHAP** | SHapley Additive exPlanations — per-feature ML explainability |
| **Optuna** | Bayesian hyperparameter optimization framework |
| **StateGraph** | LangGraph's stateful directed graph with conditional edges |
