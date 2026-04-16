import { useEffect, useRef, useState } from 'react';
import { useApi } from '../hooks/useApi';
import mermaid from 'mermaid';
import { GitBranch, Layers, Database, Brain, Cpu, Shield, ArrowRight } from 'lucide-react';

mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });

const SYSTEM_MERMAID = `graph TB
  classDef iot fill:#0e4429,stroke:#22c55e,stroke-width:2px,color:#dcfce7
  classDef supabase fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#e0e7ff
  classDef risk fill:#422006,stroke:#f97316,stroke-width:2px,color:#ffedd5
  classDef orch fill:#172554,stroke:#3b82f6,stroke-width:2px,color:#dbeafe
  classDef llm fill:#2e1065,stroke:#a855f7,stroke-width:2px,color:#f3e8ff
  classDef tools fill:#083344,stroke:#06b6d4,stroke-width:2px,color:#cffafe
  classDef human fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#ffe4e6
  classDef data fill:#1a2e05,stroke:#84cc16,stroke-width:2px,color:#ecfccb

  subgraph IoT["☁ LAYER 1 — IoT Sensors & Data Ingestion"]
    direction LR
    sensors["🌡 Smart Containers<br/>temp · humidity · shock · GPS<br/>door-open · light · vibration"]
    agg["⏱ Window Aggregation<br/>25-min sliding windows<br/>14 derived features"]
    sensors -->|"raw telemetry<br/>every 30s"| agg
  end

  subgraph SupabaseLayer["☁ SUPABASE — Cloud Data Layer"]
    direction LR
    sb_wf["📊 window_features<br/>7,408 scored windows"]
    sb_pp["📋 product_profiles<br/>temp ranges · excursion limits"]
    sb_pc["💰 product_costs<br/>unit costs · disposal · handling"]
    sb_fac["🏭 facilities<br/>cold-storage locations"]
    sb_ck["📚 compliance_knowledge<br/>417 regulatory docs (pgvector)"]
  end

  subgraph RiskEngine["⚡ LAYER 2 — Risk Scoring Engine"]
    direction LR
    fe["🔧 Feature Engineering<br/>14 features: MKT, slope,<br/>breach duration, delay ratio"]
    det["📏 Deterministic Rules<br/>7 product-aware rules<br/>temp breach · excursion · freeze"]
    ml["🤖 XGBoost Predictor<br/>Optuna-tuned · SHAP explainer<br/>spoilage probability"]
    fusion["⚖ Risk Fusion<br/>α-blend (0.45/0.55) + veto<br/>NaN→MEDIUM safety"]
    fe -->|"engineered<br/>features"| det
    fe -->|"feature<br/>vector"| ml
    det -->|"det_score<br/>+ rules fired"| fusion
    ml -->|"ml_score<br/>+ SHAP"| fusion
  end

  subgraph Orchestration["🧠 LAYER 3 — Act-First Agentic Orchestration (LangGraph)"]
    direction LR
    interpret["🔍 Interpret Risk<br/>tier + context assembly<br/>delay class · hours to breach"]
    plan["📝 Plan (Groq LLM)<br/>llama-3.3-70b-versatile<br/>tool selection + input construction"]
    execute["▶ Execute Tools<br/>result-aware cascade<br/>dependency tracking"]
    observe["👁 Observe (LLM)<br/>analyze execution results<br/>quality assessment"]
    reflect["🪞 Reflect (LLM)<br/>post-execution analysis<br/>identify gaps in REAL results"]
    revise["🔄 Revise (LLM)<br/>propose corrective steps<br/>fix failures & missing tools"]
    hreview["👤 Human Review<br/>ALWAYS for MEDIUM+<br/>confirm · augment · override"]
    output["📊 Compile Output<br/>decision summary<br/>confidence + audit trail"]
    interpret -->|"risk_input<br/>+ context"| plan
    plan -->|"LOW → skip"| output
    plan -->|"MEDIUM+"| execute
    execute -->|"tool results"| observe
    observe -->|"execution<br/>summary"| reflect
    reflect -->|"adequate"| hreview
    reflect -->|"GAP found"| revise
    revise -->|"corrective<br/>plan"| hreview
    hreview -->|"confirm or<br/>execute corrections"| output
  end

  subgraph AgentTools["🛠 LAYER 4 — Agent Tools (8 Autonomous)"]
    direction LR
    t_comply["📋 Compliance Agent<br/>RAG + pgvector search<br/>LLM interpretation"]
    t_route["🗺 Route Agent<br/>LLM-assisted selection<br/>certified carrier options"]
    t_cold["❄ Cold Storage<br/>facility matching<br/>suitability scoring"]
    t_notify["🔔 Notification<br/>multi-channel alerts<br/>revised ETA + spoilage"]
    t_sched["📅 Scheduling<br/>appointment reschedule<br/>downstream impact"]
    t_insure["💵 Insurance<br/>loss estimation<br/>claim documentation"]
    t_triage["📊 Triage<br/>multi-shipment ranking<br/>priority scoring"]
    t_approve["✋ Approval Workflow<br/>human sign-off<br/>irreversible actions"]
  end

  subgraph Dashboard["👤 LAYER 5 — Human-in-the-Loop"]
    direction LR
    dash["🖥 Operations Dashboard<br/>React + Recharts<br/>real-time monitoring"]
    approve_q["📋 Approval Queue<br/>approve/reject/select tools<br/>GDP audit trail"]
    selective["▶ Selective Execution<br/>bypasses LangGraph<br/>runs approved tools only"]
    ws["🔌 WebSocket Feed<br/>live events<br/>orchestration updates"]
  end

  agg -->|"window rows"| sb_wf
  sb_wf -->|"paginated fetch<br/>(fallback: CSV)"| fe
  sb_pp -->|"product config"| det
  sb_pp -->|"temp thresholds"| fe
  fusion -->|"tier + score<br/>+ rules"| interpret
  sb_pc -->|"cost data"| execute
  sb_fac -->|"facility data"| execute
  sb_ck -->|"regulatory vectors"| t_comply
  execute -->|"cascade context"| t_comply
  execute -->|"cascade context"| t_route
  execute -->|"cascade context"| t_cold
  execute -->|"cascade context"| t_notify
  execute -->|"cascade context"| t_sched
  execute -->|"cascade context"| t_insure
  t_approve -->|"pending"| approve_q
  approve_q -->|"approved tools"| selective
  selective -->|"results"| dash
  output -->|"decision JSON"| dash
  output -->|"events"| ws

  class sensors,agg iot
  class sb_wf,sb_pp,sb_pc,sb_fac,sb_ck supabase
  class fe,det,ml,fusion risk
  class interpret,execute,output orch
  class plan,reflect,revise,observe llm
  class hreview human
  class t_comply,t_route,t_cold,t_notify,t_sched,t_insure,t_triage,t_approve tools
  class dash,approve_q,selective,ws human`;

const DATA_FLOW_MERMAID = `graph LR
  classDef src fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#e0e7ff
  classDef process fill:#172554,stroke:#3b82f6,stroke-width:2px,color:#dbeafe
  classDef output fill:#083344,stroke:#06b6d4,stroke-width:2px,color:#cffafe
  classDef llm fill:#2e1065,stroke:#a855f7,stroke-width:2px,color:#f3e8ff

  sb["☁ Supabase<br/>window_features"] --> loader["📥 Data Loader<br/>paginated fetch"]
  csv["📁 CSV Fallback"] -.->|"if Supabase down"| loader
  loader --> fe["🔧 Feature Engineering"]
  fe --> split{{"Train/Test Split<br/>stratified by shipment"}}
  split -->|"train"| xgb["🤖 XGBoost Training<br/>Optuna hyperparams"]
  split -->|"test"| eval["📊 Evaluation<br/>AUC · F1 · SHAP"]
  xgb --> model["💾 Model Artifact<br/>xgb_model.json"]
  model --> score["⚡ Score Pipeline"]
  fe --> det["📏 Deterministic Rules"]
  det --> fuse["⚖ Fusion"]
  score --> fuse
  fuse --> scored["📊 scored_windows.csv"]
  scored --> api["🌐 FastAPI Backend"]
  api --> dash["🖥 Dashboard"]
  api --> orch["🧠 Orchestrator"]
  orch --> llm["💜 Groq LLM<br/>plan + reflect + revise + observe"]
  orch --> tools["🛠 8 Agent Tools"]
  tools -->|"results"| observe["👁 Observe"]
  observe -->|"re-plan?"| orch

  class sb,csv src
  class loader,fe,det,fuse,score,split,xgb,eval process
  class model,scored,api,dash output
  class orch,llm,tools llm`;

function LayerCard({ title, icon: Icon, iconColor, items, delay }) {
  return (
    <div className="glass-card-sm p-4 animate-slide-up" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-4 h-4 ${iconColor}`} />
        <p className="text-xs font-bold text-white">{title}</p>
      </div>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-2">
            <ArrowRight className="w-3 h-3 text-slate-600 mt-0.5 shrink-0" />
            <div>
              <p className="text-[11px] text-slate-300 font-medium">{item.name}</p>
              <p className="text-[10px] text-slate-500">{item.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GraphView() {
  const { data: mermaidData } = useApi('/graph/mermaid');
  const chartRef = useRef(null);
  const [tab, setTab] = useState('system');

  useEffect(() => {
    if (mermaidData?.mermaid && chartRef.current && tab === 'orchestrator') {
      chartRef.current.innerHTML = '';
      mermaid.render('orch-graph', mermaidData.mermaid).then(({ svg }) => {
        chartRef.current.innerHTML = svg;
      }).catch(() => {});
    }
  }, [mermaidData, tab]);

  const tabs = [
    { id: 'system', icon: Layers, label: 'Full System Architecture' },
    { id: 'dataflow', icon: Database, label: 'Data Flow Pipeline' },
    { id: 'orchestrator', icon: GitBranch, label: 'Orchestration Graph' },
  ];

  return (
    <div className="p-6 max-w-[1440px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">System Architecture</h1>
        <p className="text-sm text-slate-500 mt-0.5">5-layer agentic AI system with LLM orchestration, RAG compliance, and real-time monitoring</p>
      </div>

      <div className="flex gap-2">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all ${
              tab === t.id
                ? 'bg-gradient-to-r from-cyan-600 to-violet-600 text-white shadow-lg shadow-cyan-500/15'
                : 'glass-card-sm text-slate-400 hover:text-slate-300'
            }`}>
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'system' && <MermaidGraph mermaidStr={SYSTEM_MERMAID} id="sys" />}
      {tab === 'dataflow' && <MermaidGraph mermaidStr={DATA_FLOW_MERMAID} id="data" />}
      {tab === 'orchestrator' && (
        <div className="glass-card p-6 overflow-x-auto animate-slide-up">
          <div ref={chartRef} className="flex justify-center min-h-[300px]" />
          {!mermaidData && (
            <div className="flex items-center justify-center gap-3 text-slate-500 py-12">
              <div className="w-5 h-5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
              Loading graph...
            </div>
          )}
        </div>
      )}

      {/* Layer Detail Cards */}
      <div className="grid grid-cols-3 gap-4">
        <LayerCard title="Data & Ingestion" icon={Database} iconColor="text-emerald-400" delay={100} items={[
          { name: 'Supabase (primary)', desc: 'window_features, product_profiles, product_costs, facilities — paginated fetch with local fallback' },
          { name: 'Feature Engineering', desc: '14 derived features: MKT, temp slope, cumulative breach, delay ratio, shock/door counts' },
          { name: 'Real-time Ingest', desc: 'POST /api/ingest — scores incoming windows on-the-fly from Supabase stream listener' },
        ]} />
        <LayerCard title="Risk Scoring" icon={Cpu} iconColor="text-orange-400" delay={200} items={[
          { name: 'Deterministic Engine', desc: '7 product-aware rules: temp breach, excursion duration, freeze risk, humidity, shock, door, temp trend' },
          { name: 'XGBoost Predictor', desc: 'Optuna-tuned, SHAP-explained spoilage probability with cross-validated stratified splits' },
          { name: 'Risk Fusion', desc: 'α-blend (0.45 det / 0.55 ml) with veto override. NaN→MEDIUM safety. 4-tier classification' },
        ]} />
        <LayerCard title="Agentic Orchestration" icon={Brain} iconColor="text-violet-400" delay={300} items={[
          { name: 'LLM Provider', desc: 'Multi-provider: Groq (primary) → Ollama → OpenAI → Anthropic. Hot-configurable API keys' },
          { name: 'Plan → Reflect → Revise (all LLM)', desc: 'LLM generates plan, self-critiques against GDP/FDA, then rewrites plan to fix gaps' },
          { name: 'Execute → Observe → Re-plan', desc: 'Result-aware execution with dependency tracking. LLM observes outcomes, triggers re-plan for CRITICAL failures (max 1 loop)' },
        ]} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <LayerCard title="Agent Tools (8)" icon={Shield} iconColor="text-cyan-400" delay={400} items={[
          { name: 'Compliance (RAG)', desc: 'pgvector search on 417 regulatory docs + Groq LLM interpretation for edge-case compliance decisions' },
          { name: 'Route (LLM)', desc: 'LLM evaluates certified carrier options by product temp class, urgency, and preferred transport mode' },
          { name: 'Cold Storage / Scheduling / Notification', desc: 'Facility matching, appointment reschedule, and multi-channel alerts with cascade context' },
          { name: 'Insurance / Triage / Approval', desc: 'Loss estimation, multi-shipment priority ranking, and human-in-the-loop sign-off queue' },
        ]} />
        <LayerCard title="Dashboard & Human Loop" icon={Shield} iconColor="text-rose-400" delay={500} items={[
          { name: 'React + Recharts', desc: 'Dark-themed dashboard with live risk feed, analytics charts, orchestration viewer, and real-time WebSocket sync' },
          { name: 'Approval + Execute', desc: 'Operators approve, select individual tools, then execute — results sync to Agent Activity via WebSocket' },
          { name: 'Observation Feedback', desc: 'Dashboard shows LLM observation results, re-plan indicators, and execution mode (post_approval, human_selective)' },
        ]} />
      </div>
    </div>
  );
}

function MermaidGraph({ mermaidStr, id }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.innerHTML = '';
      mermaid.render(`${id}-${Date.now()}`, mermaidStr).then(({ svg }) => {
        ref.current.innerHTML = svg;
      }).catch(err => {
        ref.current.innerHTML = `<p class="text-red-400 text-sm p-4">Graph render error: ${err.message}</p>`;
      });
    }
  }, [mermaidStr, id]);
  return (
    <div className="glass-card p-6 overflow-x-auto animate-slide-up">
      <div ref={ref} className="flex justify-center min-h-[400px]" />
    </div>
  );
}
