# AI Cargo Monitoring - Agent Architectures

## Compliance Agent Architecture

### Overview
The Compliance Agent provides AI-powered regulatory validation for pharmaceutical shipments using a Retrieval-Augmented Generation (RAG) approach combined with LLM interpretation.

### Architecture: Unified Compliance Agent
```
┌──────────────────────────────────────────────────────────┐
│                COMPLIANCE AGENT (Unified)                │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │           LangChain Tool Wrapper                │    │
│  │  - Orchestrator interface                       │    │
│  │  - Input validation (Pydantic)                  │    │
│  │  - Audit logging (JSONL)                        │    │
│  │  - Error handling & fallbacks                   │    │
│  └─────────────────────────────────────────────────┘    │
│                           │                              │
│                           ▼                              │
│  ┌─────────────────────────────────────────────────┐    │
│  │        VectorComplianceAgent (Core Logic)       │    │
│  │                                                 │    │
│  │  ┌─────────────┐    ┌──────────────────────┐   │    │
│  │  │   Vector    │    │    LLM Interpreter   │   │    │
│  │  │   Store     │◄──►│   (Groq llama-3.3)  │   │    │
│  │  │ (Supabase   │    │                      │   │    │
│  │  │  pgvector)  │    │  - Regulation        │   │    │
│  │  │             │    │    interpretation    │   │    │
│  │  │ - FDA regs  │    │  - Decision making   │   │    │
│  │  │ - ICH guides│    │  - JSON output       │   │    │
│  │  │ - WHO/GDP   │    │                      │   │    │
│  │  └─────────────┘    └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### Core Workflow
1. **Input Processing**: Orchestrator sends shipment context (temperature, duration, product type)
2. **Semantic Search**: Build query from context → Search vector store for relevant regulations
3. **LLM Interpretation**: Feed regulations + context to LLM → Get compliance decision
4. **Structured Output**: Return compliance status, violations, approvals needed, product disposition
5. **Audit Trail**: Log all decisions for regulatory compliance

### Key Features
- **RAG-based Validation**: Semantic search over regulatory documents
- **Intelligent Fallbacks**: Mock regulations when vector store unavailable
- **Singleton Pattern**: Reuses agent instance for performance optimization
- **Dual Access**: LangChain tool (orchestrator) + Direct API (testing)
- **Comprehensive Output**: Violations, citations, approval requirements, disposition

---

## Notification Agent Architecture

### Three Core Autonomous Decisions the Agent Should Make:
1. **Stakeholder Selection** - "WHO needs to know?" (not just role-based rules)
2. **Channel Strategy** - "HOW should I reach them?" (context-aware, not severity-based)
3. **Escalation Planning** - "WHEN and HOW should I escalate?" (adaptive, not timer-based)

### Architecture: Agentic Notification Agent
```
┌──────────────────────────────────────────────────────┐
│         NOTIFICATION AGENT (Agentic Core)            │
│                                                      │
│  ┌────────────────────────────────────────────┐    │
│  │  Strategic Planner (LLM)                   │    │
│  │  - Analyzes situation                      │    │
│  │  - Decides notification strategy           │    │
│  │  - Plans escalation timeline               │    │
│  └────────────────────────────────────────────┘    │
│                      │                              │
│         ┌────────────┴────────────┐                │
│         │                         │                 │
│         ▼                         ▼                 │
│  ┌─────────────┐         ┌──────────────┐         │
│  │ Stakeholder │         │   Channel    │         │
│  │  Resolver   │         │   Optimizer  │         │
│  │  (LLM)      │         │   (LLM)      │         │
│  └─────────────┘         └──────────────┘         │
│         │                         │                 │
│         └────────────┬────────────┘                │
│                      ▼                              │
│         ┌────────────────────────┐                 │
│         │  Execution Engine      │                 │
│         │  (Message Composer +   │                 │
│         │   Channel Providers)   │                 │
│         └────────────────────────┘                 │
└──────────────────────────────────────────────────────┘
```

### Step by Step Agentic Implementation

#### 1. Strategic Planner
**Purpose**: LLM analyzes the situation and creates a notification strategy (not following hardcoded rules)

**Decisions Made**:
- Overall severity assessment (considering context, not just rules)
- Notification urgency timeline
- Risk mitigation priorities
- Budget constraints (SMS costs vs urgency)

**Input**: Full shipment context  
**Output**: Strategic plan with reasoning

#### 2. Stakeholder Resolver
**Purpose**: LLM decides WHO needs to be notified based on actual impact analysis

**Agent decides like**: 
"Hospital B admin (has critical patients + no backup) + 
On-call QA manager (can approve) + 
Logistics ops (can source backup). Skip Hospital A (has local backup), delay director notification until Monday unless QA doesn't respond in 30 min."

#### 3. Channel Optimizer
**Purpose**: LLM decides HOW to reach each stakeholder (channel mix)

**Agent decides**: "SMS primary (fastest), Email backup (documentation), no Slack (low response rate late night). Send immediately despite late hour due to urgency."

#### 4. Escalation Planner
**Purpose**: LLM creates adaptive escalation strategy (not fixed 30/60/90 min timers)

**Agent decides**: "Wait 20 min for QA Manager (shorter than usual due to urgency). 
If no response, try backup QA Manager David (10 min). 
If still no response, escalate to Director. 
If Director doesn't respond in 15 min, trigger emergency protocol."

Adaptive based on context - not fixed timers.

#### 5. Feedback Loop (Learning from Failures)
**Purpose**: Agent adapts strategy if initial approach fails with retry logic

---

## Test Scenarios

### Test Scenario 1 - Same Severity, Different Context
```
# Scenario A: Friday 11 PM, biologics, 12 patients
# Agent decides: SMS to QA Manager (fast response needed)

# Scenario B: Monday 10 AM, biologics, 12 patients  
# Agent decides: Email to QA Manager (business hours, cost-effective)

# SAME severity, DIFFERENT decision based on context
```

### Test Scenario 2 - Adaptation to Failure
```
# Initial: Email to hospital admin
# Result: Bounce (mailbox full)
# Agent autonomously decides: Contact pharmacy director instead
# Human never told it what to do on failure - it figured it out
```

### Test Scenario 3 - Custom Escalation Timeline
```
# Standard rule: 30 min escalation
# Agent sees: QA Manager responds in 15min avg, Director in 10min avg
# Agent decides: 20 min to QA, then straight to Director (skips backup QA)
# Reasoning: "Director is faster than backup QA, urgency is high"
```