# AI Cargo Monitoring -- System Architecture

## 1. High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                        SUPABASE  (Cloud Data Platform)                           │
│                                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────┐  ┌──────────────┐   │
│  │ window_features  │  │ product_profiles │  │ facilities │  │ product_costs│   │
│  │   (7,411 rows)   │  │    (6 products)  │  │ (6 sites)  │  │  (6 entries) │   │
│  └────────┬─────────┘  └────────┬─────────┘  └─────┬──────┘  └──────┬───────┘   │
│           │                     │                   │                │            │
│  ┌────────┴─────────┐  ┌───────┴─────────────┐     │                │            │
│  │ compliance_      │  │ compliance_docs     │     │                │            │
│  │ knowledge        │  │ (Storage bucket)    │     │                │            │
│  │ (pgvector)       │  │ FDA/WHO/ICH PDFs    │     │                │            │
│  └──────────────────┘  └─────────────────────┘     │                │            │
└────────────┬──────────────────────┬─────────────────┼────────────────┼────────────┘
             │                      │                 │                │
             ▼                      ▼                 ▼                ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                         LAYER 1: DATA PIPELINE                                     │
│                                                                                    │
│  src/supabase_client.py             stream listener (embedded in backend)           │
│  ├─ fetch_window_features()         ├─ Supabase Realtime subscription              │
│  ├─ fetch_product_profiles()        └─ scores internally + orchestrates MEDIUM+    │
│  ├─ fetch_product_costs()                                                          │
│  ├─ fetch_facilities()              streaming/simulate_stream.py                   │
│  └─ (all with local JSON fallback)  └─ replays CSV → Supabase for testing          │
│                                                                                    │
│  src/data_loader.py                                                                │
│  ├─ load_raw()  → tries Supabase first, falls back to data/single_table.csv       │
│  └─ split_by_shipment() → train/val/test (no temporal leakage)                     │
└────────────────────┬───────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                    LAYER 2: RISK SCORING ENGINE                                    │
│                                                                                    │
│  pipeline.py  (LangGraph pipeline: train mode or score mode)                       │
│       │                                                                            │
│       ├──→ src/feature_engineering.py                                              │
│       │    IN:  raw telemetry DataFrame                                            │
│       │    OUT: DataFrame with 14 derived features                                 │
│       │         (rolling_temp_std_3, lag_temp_1, temp_deviation_from_mean,          │
│       │          progress_pct, delay_ratio, humidity_x_temp, ...)                   │
│       │                                                                            │
│       ├──→ src/deterministic_engine.py                                             │
│       │    IN:  feature DataFrame + product_profiles                               │
│       │    OUT: det_score (0-1), det_rules_fired (list of rule names)              │
│       │    RULES:                                                                  │
│       │      temp_critical_breach   → 0.60  (outside critical limits)              │
│       │      temp_warning_breach    → 0.30  (outside normal limits)                │
│       │      temp_trend             → 0.20  (slope >1°C/hr toward breach)          │
│       │      excursion_duration     → 0.30  (cumulative min > product tolerance)   │
│       │      battery_critical       → 0.15  (battery < 20%)                        │
│       │      humidity_alert         → 0.10  (humidity > product threshold)          │
│       │      delay_temp_stress      → 0.25  (delay >120min + near breach)          │
│       │      freeze_risk            → 0.50  (freeze-sensitive + temp ≤0°C)         │
│       │                                                                            │
│       ├──→ src/predictive_model.py                                                 │
│       │    IN:  feature DataFrame (14 features)                                    │
│       │    OUT: ml_probability (0-1), shap_values (per-feature)                    │
│       │    MODEL: XGBoost + Optuna (30 trials, PR-AUC), scale_pos_weight=4.9       │
│       │                                                                            │
│       ├──→ src/risk_fusion.py                                                      │
│       │    IN:  det_score, ml_probability                                          │
│       │    OUT: fused_risk_score (0-1), risk_tier (LOW/MEDIUM/HIGH/CRITICAL)       │
│       │    FORMULA: final = 0.4 × det + 0.6 × ML, clipped [0,1]                   │
│       │    VETO:   det_score > 0.8 → final = max(final, det_score)                 │
│       │    NaN:    missing score defaults to other; both NaN → 0.5 (MEDIUM)        │
│       │                                                                            │
│       └──→ src/compliance_logger.py                                                │
│            IN:  scored DataFrame, shap_values                                      │
│            OUT: audit_logs/audit_YYYYMMDD.jsonl (immutable, append-only)            │
│            FIELDS: det_score, ml_prob, final_score, rules_fired, top_shap,         │
│                    risk_tier, telemetry_snapshot, recommended_actions               │
└────────────────────┬───────────────────────────────────────────────────────────────┘
                     │
          risk_input dict per window
          (shipment_id, container_id, window_id, leg_id, product_type,
           risk_tier, fused_risk_score, ml_spoilage_probability,
           deterministic_rule_flags, transit_phase, avg_temp_c,
           temp_slope_c_per_hr, current_delay_min, minutes_outside_range,
           delay_class, hours_to_breach, facility{}, product_cost{})
                     │
                     ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                    LAYER 3: CONTEXT ASSEMBLER                                      │
│                                                                                    │
│  src/context_assembler.py                                                          │
│  Enriches raw risk_input with domain-derived fields:                               │
│                                                                                    │
│  ┌────────────────────────────┬──────────────────────────────────────────────┐      │
│  │ Function                   │ Output                                      │      │
│  ├────────────────────────────┼──────────────────────────────────────────────┤      │
│  │ compute_delay_ratio()      │ float (current_delay_min / max_excursion)   │      │
│  │ compute_delay_class()      │ "negligible" | "developing" | "critical"    │      │
│  │ compute_hours_to_breach()  │ float (hours until temp limit hit) or None  │      │
│  │ build_window_context()     │ Merged dict: identity + telemetry + risk    │      │
│  │                            │   + profile bands + delay + facility +      │      │
│  │                            │   product_cost (from Supabase w/ fallback)  │      │
│  └────────────────────────────┴──────────────────────────────────────────────┘      │
└────────────────────┬───────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│              LAYER 4: AGENTIC ORCHESTRATION (LangGraph StateGraph)                  │
│                                                                                    │
│  orchestrator/graph.py  →  build_orchestrator()  →  compiled StateGraph            │
│  orchestrator/state.py  →  OrchestratorState TypedDict (shared mutable state)      │
│                                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │      GRAPH TOPOLOGY  (Act-First, Always-Review HITL)        │       │
│  │                                                              │       │
│  │  ┌───────────┐    ┌──────┐                                   │       │
│  │  │ interpret  │───→│ plan │                                   │       │
│  │  └───────────┘    └──┬───┘                                   │       │
│  │                      │                                       │       │
│  │            ┌─────────┴─────────┐                             │       │
│  │          LOW                 MEDIUM+                          │       │
│  │            │                   │                             │       │
│  │            ▼                   ▼                             │       │
│  │       ┌────────┐         ┌─────────┐    ┌─────────┐         │       │
│  │       │ output  │         │ execute │───→│ observe │         │       │
│  │       └────────┘         └─────────┘    └────┬────┘         │       │
│  │         (END)                                │              │       │
│  │                                              ▼              │       │
│  │                                         ┌─────────┐         │       │
│  │                                         │ reflect │         │       │
│  │                                         └────┬────┘         │       │
│  │                                  ┌───────────┴──────────┐   │       │
│  │                              adequate              gaps      │       │
│  │                                  │                  │        │       │
│  │                                  │            ┌─────┴──┐    │       │
│  │                                  │            │ revise │    │       │
│  │                                  │            └────┬───┘    │       │
│  │                                  ▼                ▼        │       │
│  │                       ┌─────────────────────────────┐       │       │
│  │                       │       human_review          │       │       │
│  │                       │  (ALWAYS for MEDIUM+)       │       │       │
│  │                       │  • adequate_pending_confirm  │       │       │
│  │                       │  • corrections_proposed      │       │       │
│  │                       └────────────┬────────────────┘       │       │
│  │                                    │                        │       │
│  │                           fallback → output → END           │       │
│  │                                                              │       │
│  │  POST-GRAPH:                                                │       │
│  │    Confirm & Close → /api/approvals/{id}/confirm            │       │
│  │    Execute Corrections → /api/approvals/{id}/execute        │       │
│  └──────────────────────────────────────────────────────────────┘       │
│                                                                                    │
│  NODE DETAIL (see Section 5 below for full I/O)                                    │
└────────────────────┬───────────────────────────────────────────────────────────────┘
                     │
                     │ execute() calls tools sequentially with cascade enrichment
                     ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                    LAYER 5: AGENT TOOLS (8 LangChain StructuredTools)               │
│                                                                                    │
│  tools/__init__.py  →  ALL_TOOLS list  +  TOOL_MAP dict                            │
│                                                                                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                  │
│  │  compliance  │ │   notify    │ │ cold_storage│ │  scheduling │                  │
│  │  agent (RAG) │ │   agent     │ │   agent     │ │    agent    │                  │
│  └──────┬───────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘                  │
│         │                │               │               │                         │
│  ┌──────┴───────┐ ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐                  │
│  │   insurance  │ │   route     │ │   triage    │ │  approval   │                  │
│  │    agent     │ │   agent     │ │   agent     │ │  workflow   │                  │
│  └──────────────┘ └─────────────┘ └─────────────┘ └─────────────┘                  │
│                                                                                    │
│  (See Section 6 below for full per-tool I/O specs)                                 │
└────────────────────┬───────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│              LAYER 6: BACKEND + DASHBOARD                                          │
│                                                                                    │
│  backend/app.py  (FastAPI, 25 endpoints + WebSocket)                               │
│  ├─ Risk data:     /api/risk/overview, /api/shipments, /api/windows                │
│  ├─ Orchestrator:  /api/orchestrator/run/{id}, /api/orchestrator/run-batch         │
│  ├─ Tools:         /api/tools/{name}/execute                                       │
│  ├─ Triage:        /api/triage/critical-shipments, /api/triage/rank                │
│  ├─ Compliance:    /api/audit-logs, /api/approvals/*                               │
│  ├─ LLM:           /api/llm/status, /api/llm/configure                             │
│  ├─ Ingest:        /api/ingest (real-time single-window from stream)               │
│  └─ WebSocket:     /ws/events (live event stream to dashboard)                     │
│                                                                                    │
│  dashboard/ (React 19 + Vite + Tailwind v4 + Recharts + Mermaid)                   │
│  ├─ Overview.jsx          KPI cards, tier pie chart, risky shipments               │
│  ├─ Monitoring.jsx        Live risk feed, alert banners                             │
│  ├─ ShipmentList.jsx      Filterable shipment table                                │
│  ├─ ShipmentDetail.jsx    Temp + risk timelines, window table                      │
│  ├─ AgentActivity.jsx     Orchestrator decisions, tool results, LLM reasoning      │
│  ├─ GraphView.jsx         Mermaid-rendered orchestration + system topology          │
│  ├─ AuditLog.jsx          Compliance records with SHAP feature importance           │
│  └─ Approvals.jsx         Human approval queue (approve/reject with justification) │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. LLM Provider System

```
orchestrator/llm_provider.py

    ENV: CARGO_LLM_PRIORITY = "groq,ollama,openai,anthropic"
    ENV: CARGO_LLM_ENABLED  = 1  (set to 0 for deterministic-only)

    ┌──────────────────────────────────────────────────┐
    │              get_llm(force_refresh)               │
    │                                                  │
    │  for provider_name in priority_list:             │
    │    ├─ groq      → GROQ_API_KEY + ChatGroq        │
    │    │              model: CARGO_GROQ_MODEL         │
    │    │              (default: llama-3.3-70b)        │
    │    │                                              │
    │    ├─ ollama    → probe localhost:11434            │
    │    │              model: CARGO_OLLAMA_MODEL        │
    │    │              (default: qwen2.5:7b)            │
    │    │                                              │
    │    ├─ openai    → OPENAI_API_KEY + ChatOpenAI     │
    │    │              model: CARGO_OPENAI_MODEL        │
    │    │              (default: gpt-4o-mini)           │
    │    │                                              │
    │    └─ anthropic → ANTHROPIC_API_KEY + ChatAnthropic│
    │                   model: CARGO_ANTHROPIC_MODEL     │
    │                   (default: claude-3-5-haiku)      │
    │                                                  │
    │  Returns: first working ChatModel or None        │
    │  Caches: _cached_llm + _cached_provider          │
    │  Recompiles graph on provider change             │
    └──────────────────────────────────────────────────┘

    Hot-reconfigurable at runtime:
      POST /api/llm/configure  { "groq_api_key": "...", "priority": "openai,groq" }
```

---

## 3. Supabase Data Integration

```
src/supabase_client.py

    ENV: SUPABASE_URL, SUPABASE_KEY (anon), SUPABASE_SERVICE_ROLE

    ┌───────────────────────┬──────────────────────┬─────────────────────────────┐
    │ Function              │ Supabase Table       │ Fallback                    │
    ├───────────────────────┼──────────────────────┼─────────────────────────────┤
    │ fetch_window_features │ window_features      │ data/single_table.csv       │
    │   (paginated, 1000/pg)│  (7,411 rows)        │                             │
    │ fetch_window_by_id    │ window_features      │ (none)                      │
    │ fetch_product_profiles│ product_profiles     │ data/product_profiles.json  │
    │ fetch_product_costs   │ product_costs        │ data/product_costs.json     │
    │ fetch_facilities      │ facilities           │ data/facilities.json        │
    │ write_risk_score      │ risk_scores (INSERT) │ (none)                      │
    └───────────────────────┴──────────────────────┴─────────────────────────────┘

    Helper wrappers (used by tools):
      load_profiles_with_fallback()  → dict keyed by product_id
      load_costs_with_fallback()     → dict keyed by product_id
      load_facilities_with_fallback()→ dict keyed by facility_id
```

---

## 4. RAG Compliance Sub-System

```
tools/compliance_agent.py  +  tools/helper/

    ┌─────────────────────────────────────────────────────────────────┐
    │                  COMPLIANCE AGENT (v2.0.0-rag)                  │
    │                                                                 │
    │  INPUT (from orchestrator via _execute):                        │
    │    shipment_id, container_id, window_id, event_type,            │
    │    risk_tier, details{}, regulatory_tags[]                      │
    │                                                                 │
    │  ┌─────────────────────────────────────────────────────┐       │
    │  │ Step 1: AUDIT LOG (always succeeds)                 │       │
    │  │   → append to audit_logs/compliance_events.jsonl    │       │
    │  │   → returns log_id (immutable, GDP-compliant)       │       │
    │  └─────────────────────────┬───────────────────────────┘       │
    │                            ▼                                    │
    │  ┌─────────────────────────────────────────────────────┐       │
    │  │ Step 2: SEMANTIC SEARCH                             │       │
    │  │                                                     │       │
    │  │  tools/helper/vector_store.py                       │       │
    │  │  ├─ Supabase pgvector (compliance_knowledge table)  │       │
    │  │  │   → RPC: match_compliance_documents()            │       │
    │  │  │   → Fallback: brute-force cosine similarity      │       │
    │  │  │                                                  │       │
    │  │  └─ Mock fallback (mock_vector_store.py)            │       │
    │  │      → 6 hardcoded FDA/ICH/WHO/GDP regulations      │       │
    │  │      → keyword overlap scoring                      │       │
    │  │                                                     │       │
    │  │  tools/helper/embeddings.py                         │       │
    │  │  └─ SentenceTransformer (all-MiniLM-L6-v2, dim=384)│       │
    │  └─────────────────────────┬───────────────────────────┘       │
    │                            ▼                                    │
    │  ┌─────────────────────────────────────────────────────┐       │
    │  │ Step 3: LLM INTERPRETATION                          │       │
    │  │                                                     │       │
    │  │  Groq API (llama-3.3-70b-versatile)                 │       │
    │  │  IN:  shipment context + retrieved regulations       │       │
    │  │  OUT: JSON { compliance_decision, severity,          │       │
    │  │              human_approval_required, approval_level, │       │
    │  │              product_disposition, violated_regulations,│       │
    │  │              required_actions, reasoning }            │       │
    │  │                                                     │       │
    │  │  Fallback: deterministic tier-based decision          │       │
    │  │    CRITICAL → violation/quarantine/director           │       │
    │  │    HIGH     → violation/quarantine/qa_manager         │       │
    │  │    MEDIUM   → borderline/investigate/none             │       │
    │  │    LOW      → compliant/release/none                  │       │
    │  └─────────────────────────┬───────────────────────────┘       │
    │                            ▼                                    │
    │  OUTPUT:                                                        │
    │    tool, status, log_id, log_path, timestamp,                   │
    │    compliance_status, human_approval_required,                   │
    │    product_disposition, violations[], regulations_checked[],     │
    │    decision_method, compliance_validation{                       │
    │      approval_level, approval_urgency,                          │
    │      deviation_report_required, applicable_citations[],         │
    │      agent_version, validation_duration_ms                      │
    │    }                                                            │
    └─────────────────────────────────────────────────────────────────┘

    Document ingestion pipeline (tools/helper/ingest_compliance_docs.py):
      Supabase Storage (compliance_docs bucket)
        → download PDF → document_parser.py (chunk, 500 words, 50 overlap)
        → embeddings.py (all-MiniLM-L6-v2 batch encode)
        → vector_store.py (INSERT into compliance_knowledge)

    Edge-case interpreter (tools/helper/llm_interpreter.py):
      For conflicting rules / borderline scenarios
      → Groq LLM with detailed system prompt
      → Returns: compliance_decision, reasoning, approval_level, disposition
```

---

## 5. Orchestration Nodes -- Detailed I/O

### 5a. interpret_risk

```
FILE: orchestrator/nodes.py :: interpret_risk()
MODE: Always deterministic

INPUT  (from state):
  risk_input.risk_tier          → "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  risk_input.fused_risk_score   → float 0-1
  risk_input.deterministic_rule_flags → ["temp_critical_breach", ...]
  risk_input.ml_spoilage_probability  → float 0-1

OUTPUT (merged into state):
  severity      → "normal" | "elevated" | "high" | "critical"
  urgency       → "routine" | "monitor" | "urgent" | "immediate"
  primary_issue → human-readable string identifying the dominant risk signal
```

### 5b. plan (agentic)

```
FILE: orchestrator/llm_nodes.py :: plan_llm()
MODE: Agentic (Groq LLM)  |  Falls back to deterministic if LLM fails

LLM SYSTEM PROMPT (condensed):
  Domain: pharma cold-chain (GDP, FDA 21 CFR, WHO TRS 961, ICH)
  Available tools: compliance_agent, notification_agent, cold_storage_agent,
                   scheduling_agent, insurance_agent, route_agent, approval_workflow
  Tool schemas: condensed required-fields-only format for token efficiency

LLM USER PROMPT:
  risk_tier, fused_score, ml_prob, rules_fired, product_type, transit_phase,
  avg_temp_c, slope, delay, primary_issue, hours_to_breach, excursion_budget, compound_risk

LLM OUTPUT FORMAT:
  { "reasoning": "...",
    "plan": [ {"tool": "...", "action": "...", "input": {...}, "reason": "..."}, ... ] }

OUTPUT (merged into state):
  draft_plan      → List[PlanStep] (step, action, tool, tool_input, reason)
  llm_reasoning   → string (LLM's reasoning trace for audit)
  requires_approval → bool (True for HIGH/CRITICAL)
  approval_reason → string
```

### 5c. plan (deterministic fallback)

```
FILE: orchestrator/nodes.py :: plan()
MODE: Template-based (no LLM needed)

TIER TEMPLATES:
  CRITICAL → [compliance, notification, cold_storage, scheduling, insurance, approval]
  HIGH     → [compliance, notification, scheduling, approval]
  MEDIUM   → [compliance, notification]
  LOW      → [] (empty plan)

Tool inputs built by _build_tool_input() using risk_input fields.
Adds route_agent for HIGH/CRITICAL at air_handoff or customs_clearance phases.

OUTPUT: same as agentic (draft_plan, requires_approval) but llm_reasoning is empty
```

### 5d. reflect (agentic — POST-EXECUTION)

```
FILE: orchestrator/llm_nodes.py :: reflect_llm()
MODE: Agentic (Groq LLM) — analyzes REAL tool results, not a hypothetical plan

LLM receives:
  - tool_results: per-tool success/failure + result summaries
  - MANDATORY tools for this tier (explicit list):
      CRITICAL: [compliance_agent, notification_agent, cold_storage_agent, insurance_agent]
      HIGH:     [compliance_agent, notification_agent]
      MEDIUM:   [compliance_agent, notification_agent]
  - OPTIONAL tools (route_agent, triage_agent, scheduling_agent):
      Explicitly marked as optional — LLM MUST NOT flag these as gaps

KEY CONSTRAINTS:
  - ONLY mandatory tools can be flagged as GAP
  - If all mandatory tools succeeded → has_gaps=false, assessment="adequate"
  - route_agent and triage_agent are never flagged as missing

OUTPUT (merged into state):
  reflection_notes → List[str] ("GAP [tool_name]: ..." or "observation: ...")
  needs_revision   → bool (True only if mandatory tools missing or failed)
```

### 5e. reflect (deterministic fallback)

```
FILE: orchestrator/nodes.py :: reflect()
MODE: Mandatory-tools-only checklist

REQUIRED TOOLS (per tier):
  CRITICAL: [compliance_agent, notification_agent, cold_storage_agent, insurance_agent]
  HIGH/MEDIUM: [compliance_agent, notification_agent]

For each required tool: check if executed and if succeeded.
Only flags tools in the mandatory list — route/triage/scheduling never flagged.

OUTPUT: reflection_notes (same format as agentic), needs_revision (bool)
```

### 5f. revise (agentic — CORRECTIVE-ONLY)

```
FILE: orchestrator/llm_nodes.py :: revise_llm()  |  fallback: nodes.py :: revise()
MODE: Agentic (Groq LLM)  |  Falls back to deterministic

AGENTIC MODE (revise_llm):
  LLM receives:
    - tool_results (what actually ran and their outcomes)
    - reflection_notes (GAP annotations from reflect)
    - MANDATORY tools for this tier (explicit list)
  LLM proposes ONLY corrective steps:
    - Missing mandatory tools that weren't executed
    - Failed mandatory tools that need retry
    - NEVER proposes route_agent, triage_agent, scheduling_agent
      unless they specifically FAILED in first execution
  Hard filter: code rejects any LLM-proposed tool not in mandatory_set ∪ failed_set
  Returns empty steps if all mandatory tools succeeded

DETERMINISTIC FALLBACK (revise):
  Same mandatory-only logic: scans reflection_notes for GAP keywords,
  only inserts tools from the tier-specific mandatory list.
  Skips already-succeeded tools.

OUTPUT (merged into state):
  revised_plan → List[PlanStep] (corrective steps only, not full rewrite)
  active_plan  → same as revised_plan
  plan_revised → True
  needs_revision → False (if no corrections needed)
```

### 5g. execute (with cascade enrichment)

```
FILE: orchestrator/nodes.py :: execute()
MODE: Always deterministic (sequential tool invocation)

FOR EACH STEP in active_plan:
  1. base_input = step["tool_input"]           ← from LLM or template
  2. enriched  = _enrich_tool_input(...)        ← cascade enrichment
  3. result    = TOOL_MAP[tool_name].invoke(enriched)
  4. cascade_ctx[tool_name] = result            ← feeds downstream tools
  5. if error → failed_tools.add(tool_name)    ← dependency tracking

DEPENDENCY AWARENESS (_DEPENDS_ON map):
  notification_agent depends on cold_storage_agent
  scheduling_agent   depends on cold_storage_agent
  insurance_agent    depends on compliance_agent
  If upstream tool failed, downstream tool gets injected warning:
    "_upstream_warning": "cold_storage_agent failed: ..."

CASCADE ENRICHMENT (_enrich_tool_input):
  ┌────────────────────┬──────────────────────────────────────────────────┐
  │ Target Tool        │ What Gets Injected                              │
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ compliance_agent   │ product_category, current_temp_c,               │
  │                    │ minutes_outside_range, transit_phase,            │
  │                    │ spoilage_probability, at_risk_value              │
  │                    │ (ensures RAG search gets full context)           │
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ notification_agent │ revised_eta (computed), spoilage_probability,    │
  │                    │ facility_name (from cold_storage result),        │
  │                    │ advance_notice_hours, temp_range (from cold_storage)│
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ scheduling_agent   │ revised_eta, affected_facilities (from cold_    │
  │                    │ storage), advance_notice_hours, temp_range,      │
  │                    │ delay_class, hours_to_breach, risk_tier          │
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ insurance_agent    │ supporting_evidence (compliance log_id),         │
  │                    │ estimated_loss_usd (from product_cost × spoilage)│
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ cold_storage_agent │ location_hint, hours_to_breach, avg_temp_c,     │
  │                    │ temp_slope_c_per_hr                              │
  ├────────────────────┼──────────────────────────────────────────────────┤
  │ approval_workflow  │ proposed_actions (actual tool result summaries   │
  │                    │ from cascade_ctx, not generic descriptions)      │
  └────────────────────┴──────────────────────────────────────────────────┘

OUTPUT (merged into state):
  tool_results    → List[ToolResult] (tool, input, result, success)
  execution_errors→ List[str]
  cascade_context → Dict[tool_name → result_dict]
  approval_id     → str or None
```

### 5g-bis. observe (agentic)

```
FILE: orchestrator/llm_nodes.py :: observe_llm()
MODE: Agentic (Groq LLM)  |  Falls back to deterministic no-op

LLM receives:
  - tool_results (per-tool success/failure + result summaries)
  - execution_errors (list of error messages)
  - risk_tier, active_plan

LLM OUTPUT FORMAT:
  { "adequate": bool,
    "issues": ["..."],
    "actions": ["..."] }

In the new Act-First pipeline, observe runs BEFORE reflect.
Its output feeds into reflect_llm for mandatory tool gap analysis.
No replan loop — corrections are handled via human_review node.

OUTPUT (merged into state):
  observation         → str (LLM summary of execution quality)
  observation_issues  → List[str]
  observation_actions → List[str]
```

### 5h. fallback

```
FILE: orchestrator/nodes.py :: build_fallback()
MODE: Always deterministic

Creates a minimal backup plan if primary execution had errors:
  Step 1: notification_agent  → escalate to on-call ops manager
  Step 2: compliance_agent    → log the escalation event

OUTPUT: fallback_plan → List[PlanStep]
```

### 5i. output (compile)

```
FILE: orchestrator/nodes.py :: compile_output()
MODE: Always deterministic

Assembles the final orchestrator decision JSON:
  - shipment_id, container_id, window_id, leg_id
  - risk_tier, fused_risk_score, ml_spoilage_probability
  - decision_summary (human-readable sentence)
  - key_drivers (SHAP feature list)
  - draft_plan, reflection_notes, revised_plan
  - actions_taken [{tool, input, result}]
  - fallback_plan
  - llm_reasoning (full LLM thought trace)
  - cascade_context (full tool results for audit)
  - cascade_summary (truncated to 200 chars per tool for display)
  - audit_log_summary, confidence (0.0-1.0), timestamp
  - awaiting_approval (bool — True for all MEDIUM+ tiers)
  - review_status ("corrections_proposed" | "adequate_pending_confirmation")

For MEDIUM+ tiers:
  - awaiting_approval is ALWAYS True (human must review)
  - review_status set based on whether reflect found gaps
  - confidence set to 0.70 (corrections pending) or 0.80 (adequate, awaiting confirm)

CONFIDENCE RULES:
  LOW tier, no tools                    → 0.95
  MEDIUM+, adequate (awaiting confirm)  → 0.80
  MEDIUM+, corrections proposed         → 0.70
  Partial success (errors)              → 0.50
```

---

## 6. Agent Tools -- Detailed I/O Specs

### 6a. compliance_agent (RAG-powered)

```
FILE: tools/compliance_agent.py  +  tools/helper/*
DATA: Supabase pgvector (compliance_knowledge) + mock fallback

INPUT:
  shipment_id         str       Shipment identifier
  container_id        str       Container identifier
  window_id           str       Time window identifier
  event_type          str       "risk_assessment" | "excursion" | "action_taken"
  risk_tier           str       "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  details             dict      product_category, current_temp_c, minutes_outside_range,
                                transit_phase, spoilage_probability, at_risk_value, ...
  regulatory_tags     list[str] ["GDP", "FDA_21CFR11", "WHO_PQS", "DSCSA"]

OUTPUT:
  tool                str       "compliance_agent"
  status              str       "completed" | "audit_only"
  log_id              str       "CL-YYYYMMDDHHMMSSffffff" (immutable audit ID)
  log_path            str       path to compliance_events.jsonl
  compliance_status   str       "compliant" | "violation" | "borderline"
  human_approval_required bool
  product_disposition str       "release" | "quarantine" | "destroy" | "investigate"
  violations          list      [{violation_type, severity, regulation, description}]
  regulations_checked list[str] regulations evaluated
  decision_method     str       "vector_search_llm" | "deterministic_fallback" | "mock_regs_*"
  compliance_validation dict    Full sub-object with citations, approval_level, reasoning
```

### 6b. route_agent

```
FILE: tools/route_agent.py
DATA: product_profiles (Supabase → local fallback)

INPUT:
  shipment_id    str       Shipment identifier
  container_id   str       Container identifier
  current_leg_id str       Current leg being evaluated
  reason         str       Why rerouting is considered
  product_id     str?      Product ID (for temp-class lookup)
  preferred_mode str?      Preferred transport mode

OUTPUT:
  tool              str    "route_agent"
  status            str    "recommendation_generated"
  recommended_route str    Route description
  carrier           str    Carrier name (temp-class-aware)
  eta_change_hours  float  ETA impact
  temp_class        str    "frozen" | "refrigerated" | "CRT"
  selection_method  str    "llm" | "rule_based"
  selection_rationale str  Why this carrier/route was selected
  requires_approval bool   True for mode changes

LOGIC: Looks up product temp_class from profiles → builds safe candidate options
       from _ROUTE_TABLE → if an LLM is available, asks it to choose ONE provided
       option only based on product safety, urgency, and preferred mode →
       falls back to deterministic urgency sorting if LLM is unavailable/fails
```

### 6c. cold_storage_agent

```
FILE: tools/cold_storage_agent.py
DATA: facilities + product_profiles (Supabase → local fallback)

INPUT:
  shipment_id          str     Shipment identifier
  container_id         str     Container identifier
  product_id           str     Product ID (for temp compatibility check)
  location_hint        str?    Airport code or transit phase
  urgency              str     "critical" | "high" | "medium"
  hours_to_breach      float?  Hours until temp limit
  avg_temp_c           float?  Current average temperature
  temp_slope_c_per_hr  float?  Temperature rate of change

OUTPUT:
  tool                          str    "cold_storage_agent"
  status                        str    "facility_identified"
  recommended_facility          str    Facility name
  recommended_facility_id       str    Facility ID
  location                      str    Facility location
  temp_range_supported          str    e.g., "2-8°C"
  suitability_score             float  0-100 composite score
  suitability_tier              str    "ideal" | "acceptable" | "marginal"
  advance_notice_required_hours float  Lead time required
  transfer_window_hours         float  Available transfer window
  alternative_facilities        list   Backup options
  compliance_flags              list   GDP/regulatory flags

LOGIC: Scores all facilities by temp compatibility × distance × capacity × urgency,
       filters by product temp range, returns top candidate + alternatives
```

### 6d. notification_agent (AGENTIC — LLM + Multi-Channel Delivery)

```
FILE: tools/notification_agent.py + tools/helper/notification/
DATA: Groq LLM (stakeholder selection + message composition)

INPUT:
  shipment_id          str       Shipment identifier
  container_id         str       Container identifier
  risk_tier            str       "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  recipients           list[str] ["ops_team", "management", "clinic"]
  message              str       Alert message text
  channel              str       "dashboard" | "email" | "sms" | "slack"
  revised_eta          str?      ISO timestamp
  spoilage_probability float?    0-1
  facility_name        str?      From cold_storage cascade

OUTPUT (agentic mode — Groq available + email/Slack configured):
  tool                     str    "notification_agent"
  status                   str    "notifications_sent"
  notification_batch_id    str    Batch ID for tracking
  total_notifications      int    Total sent
  successful_deliveries    int    Delivered count
  failed_deliveries        int    Failed count
  notifications_sent       list   [{notification_id, recipient_role, recipient_name,
                                    channel, subject, status, sent_at}]
  escalation_required      bool   Whether escalation is needed
  regulatory_notifications bool   Whether regulatory bodies were notified
  audit_trail_entries      int    FDA 21 CFR Part 11 audit records count
  agentic_workflow         bool   True (confirms agentic mode)

OUTPUT (fallback mode — no LLM or email config):
  tool             str    "notification_agent"
  status           str    "notification_queued"
  alert_payload    dict   Full payload with revised_eta, spoilage, facility
  message_preview  str    First 200 chars
  delivered        bool   False
  agentic_workflow bool   False
```

### 6e. scheduling_agent

```
FILE: tools/scheduling_agent.py
DATA: facilities + product_costs (Supabase → local fallback)

INPUT:
  shipment_id                    str       Shipment identifier
  product_id                     str       Product ID
  affected_facilities            list[str] ["Boston General (Boston, MA)"]
  original_eta                   str       Original ETA
  revised_eta                    str?      Revised ETA (from cascade)
  reason                         str       Why rescheduling needed
  delay_class                    str?      "negligible" | "developing" | "critical"
  hours_to_breach                float?    Hours until temp limit
  ml_spoilage_probability        float?    0-1
  risk_tier                      str?      "HIGH" | "CRITICAL"
  advance_notice_required_hours  float?    From cold_storage cascade
  temp_range_supported           str?      From cold_storage cascade

OUTPUT:
  tool                          str    "scheduling_agent"
  status                        str    "recommendations_generated"
  facility_recommendations      list   Per-facility reschedule details
  routing_decision              str    "reroute" | "delay" | "cancel"
  priority_tier                 str    "critical" | "high" | "standard"
  priority_score                float  0-100
  financial_impact_estimate_usd float  Estimated cost impact
  compliance_flags              list   Regulatory flags
  actions_required              list   Specific actions needed
  summary_line                  str    One-line summary
  substitute_available          bool   Whether substitutes exist
```

### 6f. insurance_agent

```
FILE: tools/insurance_agent.py
DATA: scored_windows.csv + product_costs + facilities (Supabase → local)

INPUT:
  shipment_id          str       Shipment identifier
  container_id         str       Container identifier
  product_id           str       Product ID
  risk_tier            str       "HIGH" | "CRITICAL"
  incident_summary     str       What happened
  leg_id               str?      Specific transport leg
  spoilage_probability float?    0-1
  estimated_loss_usd   float?    Pre-computed loss (from cascade)
  supporting_evidence  list[str] [compliance log_id] (from cascade)

OUTPUT:
  tool                       str    "insurance_agent"
  status                     str    "claim_draft_prepared"
  claim_id                   str    "CLM-XXXXXXXX"
  estimated_loss_usd         float  Total computed loss
  loss_breakdown             dict   {product, disposal, handling, downstream_disruption}
  replacement_lead_time_days int    How long to replace
  substitute_available       bool   Whether alternatives exist
  excursion_summary          dict   {total_minutes, max_temp, legs_affected}
  next_steps                 list   Actions for claim processing
```

### 6g. triage_agent

```
FILE: tools/triage_agent.py
DATA: scored_windows.csv + product_profiles (Supabase → local)

INPUT:
  shipments   list[ShipmentRiskSummary]   List of shipments to rank:
                shipment_id (str), risk_tier (str), fused_risk_score (float),
                product_id (str), container_id? (str), transit_phase? (str)
  enrich      bool                        Enrich with scored_windows.csv data

OUTPUT:
  tool                           str    "triage_agent"
  status                         str    "ranked"
  total_shipments                int    Total input count
  critical_count                 int    CRITICAL tier count
  high_count                     int    HIGH tier count
  shipments_requiring_action     int    Count above MEDIUM
  priority_list                  list   Ranked shipments with urgency_label
  recommended_orchestration_order list  Ordered shipment IDs for processing
```

### 6h. approval_workflow

```
FILE: tools/approval_workflow.py
DATA: In-memory _PENDING_APPROVALS dict

INPUT:
  shipment_id        str       Shipment identifier
  action_description str       What needs approval
  risk_tier          str       "HIGH" | "CRITICAL"
  urgency            str       "urgent" | "immediate"
  proposed_actions   list[str] Action summaries (from cascade)
  justification      str       Why approval is needed
  requested_by       str       "orchestrator" (default)

OUTPUT:
  tool         str    "approval_workflow"
  status       str    "approval_requested"
  approval_id  str    "APR-XXXXXXXX" (UUID-based)
  message      str    Human-readable status

POST-REVIEW HUMAN ACTIONS (backend/app.py):

  1. CONFIRM (POST /api/approvals/{id}/confirm):
     First pass adequate, no corrections needed. Updates history entry
     with status="confirmed", _execution_mode="confirmed".
     No tools re-executed.

  2. EXECUTE CORRECTIONS (POST /api/approvals/{id}/execute):
     Human selects corrective tools from proposed list.
     Runs run_orchestrator_selective() — bypasses LangGraph entirely.
     (interpret → execute → observe → compile, no LLM plan overwrite)
     Replaces original history entry in-place.
     If selected_tools is empty → treated as confirm.

  3. DISMISS (same endpoint, empty tools):
     Equivalent to confirm — first pass accepted as sufficient.
```

---

## 7. Conditional Edge Logic (Act-First, Always-Review)

```
orchestrator/graph.py :: _should_execute(state) + _should_revise(state)

  ┌──────────────┐
  │     plan      │
  └──────┬───────┘
         │
         ├── tier == LOW ?
         │   └── YES → "skip_to_output"  (no tools, monitoring only)
         │
         └── MEDIUM/HIGH/CRITICAL ?
             └── "execute"  (act first — run tools immediately)

  execute ──→ observe ──→ reflect  (always sequential)

  ┌──────────────┐
  │   reflect     │
  └──────┬───────┘
         │
         ├── needs_revision == True ?
         │   └── YES → "revise"  (propose corrective steps for mandatory gaps)
         │              revise ──→ "human_review"
         │
         └── needs_revision == False ?
             └── "human_review"  (first pass adequate, confirm)

  human_review ──→ fallback ──→ output ──→ END
  (Pipeline always terminates here. Human acts POST-GRAPH.)

  POST-GRAPH HUMAN ACTIONS:
    /api/approvals/{id}/confirm  → close without re-execution
    /api/approvals/{id}/execute  → run selected corrective tools
```

---

## 8. Cascade Data Flow Example (CRITICAL Tier)

**Act-First HITL:** For CRITICAL tier, steps 1–6 below run **immediately** (act first). After execution, observe → reflect analyzes results. human_review node pauses for human to confirm (if adequate) or approve corrections (if gaps found). Corrective tools run only via `POST /api/approvals/{id}/execute`.

```
Step 1: compliance_agent
  IN:  {shipment_id, risk_tier:"CRITICAL", details:{product_category, temp, ...}}
  OUT: {log_id:"CL-...", compliance_status:"violation", disposition:"quarantine"}
          │
          │  log_id flows to insurance_agent
          ▼
Step 2: cold_storage_agent
  IN:  {product_id, location_hint:"BOS", urgency:"critical", hours_to_breach:2.1}
  OUT: {recommended_facility:"ColdVault Boston", advance_notice:4h, temp_range:"2-8°C"}
          │
          │  facility name, advance_notice, temp_range flow to notification + scheduling
          ▼
Step 3: notification_agent
  IN:  {message + " Backup facility: ColdVault Boston. Advance notice: 4h."}
  OUT: {status:"notification_queued"}
          │
          ▼
Step 4: insurance_agent
  IN:  {supporting_evidence:["CL-..."], estimated_loss_usd: 110500}
  OUT: {claim_id:"CLM-...", loss_breakdown:{product:85000, disposal:3000, ...}}
          │
          ▼
Step 5: scheduling_agent
  IN:  {affected_facilities:["ColdVault Boston (Boston, MA)"], advance_notice:4h}
  OUT: {routing_decision:"reroute", facility_recommendations:[...]}
          │
          ▼
Step 6: approval_workflow
  IN:  {proposed_actions:["compliance_agent: completed", "cold_storage_agent: ..."]}
  OUT: {approval_id:"APR-...", status:"approval_requested"}
```

---

## 9. Risk Tier Decision Matrix

```
┌──────────┬─────────┬──────────────────────────────┬──────────────────────────────┐
│ Tier     │ Score   │ Mandatory Tools              │ Human Review                 │
├──────────┼─────────┼──────────────────────────────┼──────────────────────────────┤
│ CRITICAL │ 0.8-1.0 │ compliance, notification,    │ ALWAYS (act-first, review    │
│          │         │ cold_storage, insurance       │ after execution). Confirm or │
│          │         │ + optional: scheduling, route │ approve corrections.         │
├──────────┼─────────┼──────────────────────────────┼──────────────────────────────┤
│ HIGH     │ 0.6-0.8 │ compliance, notification     │ ALWAYS (same pattern)        │
│          │         │ + optional: scheduling, route │                              │
├──────────┼─────────┼──────────────────────────────┼──────────────────────────────┤
│ MEDIUM   │ 0.3-0.6 │ compliance, notification     │ ALWAYS (confirm or correct)  │
│          │         │                               │                              │
├──────────┼─────────┼──────────────────────────────┼──────────────────────────────┤
│ LOW      │ 0.0-0.3 │ (none)                       │ NO — monitoring only         │
│          │         │                               │ Bypasses human_review node   │
└──────────┴─────────┴──────────────────────────────┴──────────────────────────────┘
```
