# AI Cargo Monitoring -- Progress Report & Task Distribution

## System Layers

```
L1  Data + Risk Engine        DONE     Rahul
L2  Agent Tools (8 tools)     DONE     Rahul
L3  Orchestration Agent       DONE     Rahul (deterministic) + Teammate (LLM upgrade)
L4  FastAPI Backend            DONE     Rahul
L5  React Dashboard            DONE     Rahul
L6  Integration + E2E Tests   DONE     Rahul (verified in venv)
```

---

## Agent & Tool Registry

Every agent is a **LangChain StructuredTool** with a Pydantic input schema.
The orchestrator invokes them via `tool.invoke(input_dict)`.

| # | Agent Name | File | What it does | Input Schema | When it's called |
|---|-----------|------|-------------|--------------|-----------------|
| 1 | **route_agent** | `tools/route_agent.py` | Recommends alternative routes/carriers with ETA impact | `RouteInput(shipment_id, container_id, current_leg_id, reason, preferred_mode?)` | CRITICAL/HIGH + transit phase is air_handoff or customs_clearance |
| 2 | **cold_storage_agent** | `tools/cold_storage_agent.py` | Finds backup cold-storage facilities near shipment | `ColdStorageInput(shipment_id, container_id, product_id, location_hint?, urgency)` | CRITICAL when temp breach detected |
| 3 | **notification_agent** | `tools/notification_agent.py` | Sends alerts to ops_team, management, clinic, hospital | `NotificationInput(shipment_id, container_id, risk_tier, recipients[], message, channel)` | CRITICAL (ops+mgmt+clinic), HIGH (ops), MEDIUM (dashboard only) |
| 4 | **compliance_agent** | `tools/compliance_agent.py` | Writes immutable JSONL audit record (GDP, FDA, WHO) | `ComplianceInput(shipment_id, container_id, window_id, event_type, risk_tier, details{}, regulatory_tags[])` | Every MEDIUM/HIGH/CRITICAL event (first action always) |
| 5 | **scheduling_agent** | `tools/scheduling_agent.py` | Generates reschedule recommendations for downstream facilities | `SchedulingInput(shipment_id, product_id, affected_facilities[], original_eta, revised_eta?, reason)` | When delay threatens clinic/hospital delivery |
| 6 | **insurance_agent** | `tools/insurance_agent.py` | Prepares claim documentation with audit references | `InsuranceInput(shipment_id, container_id, product_id, risk_tier, incident_summary, estimated_loss_usd?, supporting_evidence[])` | CRITICAL + excursion_duration rule fired |
| 7 | **triage_agent** | `tools/triage_agent.py` | Ranks multiple shipments by urgency (batch prioritization) | `TriageInput(shipments: List[ShipmentRiskSummary])` | When orchestrator processes multiple windows |
| 8 | **approval_workflow** | `tools/approval_workflow.py` | Creates pending approval request for human sign-off | `ApprovalInput(shipment_id, action_description, risk_tier, urgency, proposed_actions[], justification)` | Every CRITICAL/HIGH plan (last action before output) |

### How tools connect to the orchestrator

```
orchestrator/nodes.py :: execute()
    ↓ for each step in active_plan:
    ↓   tool = TOOL_MAP[step["tool"]]      ← imported from tools/__init__.py
    ↓   result = tool.invoke(step["tool_input"])
    ↓   results.append(ToolResult(...))
    ↓
    ↓ if tool is approval_workflow → return early (wait for human)
```

---

## Orchestration Agent -- Node-by-Node

| Node | File:Function | What it does | Output State Keys |
|------|--------------|-------------|-------------------|
| **interpret** | `orchestrator/nodes.py :: interpret_risk()` | Parses risk engine JSON, classifies severity (critical/high/elevated/normal), identifies primary issue from rule flags | `severity, urgency, primary_issue` |
| **plan** | `orchestrator/nodes.py :: plan()` | Generates draft plan from tier templates (4-6 steps for CRITICAL, 3 for HIGH, 2 for MEDIUM, 0 for LOW). Adds insurance/route steps conditionally | `draft_plan, requires_approval, approval_reason` |
| **reflect** | `orchestrator/nodes.py :: reflect()` | Checks plan against 5-point compliance checklist: compliance_covered, notification_included, approval_for_irreversible, has_fallback, no_empty_steps | `reflection_notes` |
| **revise** | `orchestrator/nodes.py :: revise()` | Patches plan to fix gaps (adds missing compliance/notification/approval steps). Only runs if reflect found "GAP" notes | `revised_plan, plan_revised, active_plan` |
| **execute** | `orchestrator/nodes.py :: execute()` | Calls each tool in active_plan sequentially via LangChain invoke(). Stops early if approval_workflow returns | `tool_results, execution_errors, approval_id` |
| **fallback** | `orchestrator/nodes.py :: build_fallback()` | Creates minimal 2-step backup: escalate to ops manager + log escalation | `fallback_plan` |
| **output** | `orchestrator/nodes.py :: compile_output()` | Assembles final JSON matching system_prompt.md output format | `final_output, decision_summary, confidence` |

### Conditional Edges

```
reflect ──→ revise       (if reflection_notes contain "GAP" AND not already revised)
reflect ──→ execute      (if plan passes all checks)
reflect ──→ output       (if tier is LOW, skip everything)
```

---

## Risk Scoring Pipeline -- Node-by-Node

| Node | File | What it does |
|------|------|-------------|
| **ingest** | `pipeline.py → src/data_loader.py` | Load CSV, validate schema, shipment-stratified split |
| **engineer** | `pipeline.py → src/feature_engineering.py` | 14 derived features: temp_deviation, cumulative_breach, rolling stats, lag transforms |
| **deterministic** | `pipeline.py → src/deterministic_engine.py` | 7 product-aware rules using WHO thresholds from `data/product_profiles.json` |
| **ml_train** | `pipeline.py → src/predictive_model.py` | XGBoost + 30-trial Optuna tuning (PR-AUC), only in train mode |
| **ml_score** | `pipeline.py → src/predictive_model.py` | Predict spoilage probability on all windows |
| **fuse** | `pipeline.py → src/risk_fusion.py` | `0.4*det + 0.6*ML`, deterministic veto if det > 0.8 |
| **explain** | `pipeline.py → src/predictive_model.py` | SHAP values per prediction for regulatory explainability |
| **compliance** | `pipeline.py → src/compliance_logger.py` | Append JSONL audit record per window |
| **summary** | `pipeline.py` | Print tier counts, save `artifacts/scored_windows.csv` |

---

## Backend API Endpoints

| Endpoint | Method | Purpose | File |
|----------|--------|---------|------|
| `/api/risk/overview` | GET | Tier distribution, KPIs, top risky shipments | `backend/app.py` |
| `/api/shipments` | GET | All shipments, filterable by `risk_tier` | `backend/app.py` |
| `/api/shipments/{id}/windows` | GET | All windows for a shipment | `backend/app.py` |
| `/api/windows` | GET | Windows, filterable by tier/product, paginated | `backend/app.py` |
| `/api/risk/score-window/{id}` | GET | Risk engine output for orchestrator | `backend/app.py` |
| `/api/orchestrator/run/{id}` | POST | Run orchestration agent on a window | `backend/app.py` |
| `/api/orchestrator/run-batch` | POST | Orchestrate multiple windows | `backend/app.py` |
| `/api/orchestrator/history` | GET | Recent orchestrator decisions | `backend/app.py` |
| `/api/tools/{name}/execute` | POST | Execute any agent tool directly | `backend/app.py` |
| `/api/graph/mermaid` | GET | Orchestrator graph as Mermaid string | `backend/app.py` |
| `/api/graph/topology` | GET | Full 5-layer system topology JSON | `backend/app.py` |
| `/api/audit-logs` | GET | Compliance audit records | `backend/app.py` |
| `/api/approvals/pending` | GET | Pending human approval requests | `backend/app.py` |
| `/api/approvals/{id}/decide` | POST | Approve or reject an action | `backend/app.py` |
| `/ws/events` | WebSocket | Real-time event stream | `backend/app.py` |

---

## Dashboard Pages

| Page | Component File | What it shows |
|------|---------------|---------------|
| Overview | `dashboard/src/components/Overview.jsx` | KPI cards, tier pie chart, top risky shipments bar chart, summary table |
| Monitoring | `dashboard/src/components/Monitoring.jsx` | Live risk feed, critical alert banner, KPI strip |
| Shipments | `dashboard/src/components/ShipmentList.jsx` | Filterable shipment list with tier badges |
| Shipment Detail | `dashboard/src/components/ShipmentDetail.jsx` | Temp + risk score timelines, window table |
| Agent Activity | `dashboard/src/components/AgentActivity.jsx` | Run orchestrator, view decisions, tool results, reflection notes |
| System Graph | `dashboard/src/components/GraphView.jsx` | Mermaid-rendered system + orchestrator graphs |
| Audit Log | `dashboard/src/components/AuditLog.jsx` | Compliance records with SHAP features |
| Approvals | `dashboard/src/components/Approvals.jsx` | Human approval queue (approve/reject) |

---

## Task Ownership

### Rahul -- Risk Engine, Tools, Backend, Dashboard, Orchestrator (deterministic)

| # | Task | Status | File(s) |
|---|------|--------|---------|
| 1 | Synthetic data audit & EDA | DONE | `notebooks/01_eda_data_quality.ipynb` |
| 2 | Product profiles (WHO thresholds) | DONE | `data/product_profiles.json` |
| 3 | Feature engineering module | DONE | `src/feature_engineering.py` |
| 4 | Deterministic rule engine | DONE | `src/deterministic_engine.py` |
| 5 | Predictive ML model (XGBoost) | DONE | `src/predictive_model.py` |
| 6 | Risk fusion layer | DONE | `src/risk_fusion.py` |
| 7 | Compliance logger | DONE | `src/compliance_logger.py` |
| 8 | LangGraph risk-scoring pipeline | DONE | `pipeline.py` |
| 9 | Agent tools (8 LangChain tools) | DONE | `tools/*.py` |
| 10 | Pydantic schemas | DONE | `backend/models.py` |
| 11 | FastAPI backend (15 endpoints) | DONE | `backend/app.py` |
| 12 | React dashboard (8 pages) | DONE | `dashboard/src/components/*.jsx` |
| 13 | Orchestration agent (deterministic) | DONE | `orchestrator/*.py` |
| 14 | Graph visualization notebook | DONE | `notebooks/02_orchestration_graphs.ipynb` |
| 15 | Integration test (E2E in venv) | DONE | Verified all modules import + run |

### Teammate -- Orchestration Agent (LLM upgrade)

| # | Task | Status | Depends on | Notes |
|---|------|--------|------------|-------|
| A | System prompt design | DONE | -- | `system_prompt.md` |
| B | Swap plan/reflect nodes to use LLM | OPEN | A, 13 | Replace deterministic logic in `orchestrator/nodes.py` with LLM calls |
| C | Add LangSmith tracing | OPEN | B | Wrap graph with LangSmith callbacks for observability |
| D | End-to-end LLM orchestration tests | OPEN | B, C | Test with real OpenAI/Anthropic API key |

---

## Pickable Tasks for Team Members

**Want to contribute? Pick any task below and update this file.**

| Task | Difficulty | Impact | Where to start |
|------|-----------|--------|----------------|
| Upgrade `route_agent` to call real routing API | Medium | High | `tools/route_agent.py` -- replace `_execute()` mock |
| Upgrade `cold_storage_agent` to query facility database | Medium | High | `tools/cold_storage_agent.py` -- replace mock FACILITIES |
| Upgrade `notification_agent` to send real emails/SMS | Medium | Medium | `tools/notification_agent.py` -- integrate Twilio/SendGrid |
| Add LLM-powered plan/reflect nodes | Hard | Very High | `orchestrator/nodes.py` -- swap plan() and reflect() to call GPT-4/Claude |
| Add LangSmith tracing to orchestrator | Easy | Medium | `orchestrator/graph.py` -- add LangSmith callbacks |
| Improve data: increase shock/door_open variance | Easy | Medium | Re-run data generation with updated rules |
| Add P03 (CRT) spoilage scenarios to dataset | Medium | Medium | Update data generation script |
| Add real-time WebSocket push to dashboard | Medium | High | `backend/app.py` _broadcast() + `dashboard/src/hooks/useApi.js` |
| Build CI/CD pipeline (GitHub Actions) | Medium | Medium | Add `.github/workflows/test.yml` |
| Deploy backend to Render/Railway | Medium | High | Add `Dockerfile`, update `Procfile` |

---

## Data Quality Actions (pending)

| Issue | Priority | Owner |
|-------|----------|-------|
| shock_count 99.7% zeros | Medium | Rahul (data gen update) |
| door_open_count 99.8% zeros | Medium | Rahul (data gen update) |
| P03 zero spoilage events | Low | Rahul |
| Add product temp ranges to CSV | Low | Rahul |
