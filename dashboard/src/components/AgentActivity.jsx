import { useState, useCallback, useEffect } from 'react';
import { useApi, getApi, postApi, deleteApi } from '../hooks/useApi';
import { useWebSocket } from '../hooks/useWebSocket';
import TierBadge from './TierBadge';
import {
  Play, Zap, CheckCircle, ChevronDown, ChevronUp, Building2, DollarSign,
  Shield, Brain, BookOpen, AlertTriangle, FileCheck, Navigation,
  Activity, Bell, Clock, BarChart3, ArrowRight, Bot, Cpu, MapPin,
  RefreshCw, Eye, RotateCcw, Wifi, WifiOff, XCircle,
} from 'lucide-react';

/* ── Agent Tool Registry ───────────────────────────────────────────── */

const AGENTS = [
  { id: 'compliance_agent', name: 'Compliance Agent', icon: FileCheck, color: 'violet', desc: 'GDP/FDA validation using regulatory vector search + LLM interpretation' },
  { id: 'route_agent', name: 'Route Agent', icon: Navigation, color: 'cyan', desc: 'Safe route selection from certified carrier options by product temp class' },
  { id: 'cold_storage_agent', name: 'Cold Storage', icon: Building2, color: 'indigo', desc: 'Finds backup cold-storage facilities ranked by suitability and proximity' },
  { id: 'notification_agent', name: 'Notification', icon: Bell, color: 'amber', desc: 'Multi-channel alerts to stakeholders with revised ETA and spoilage data' },
  { id: 'scheduling_agent', name: 'Scheduling', icon: Clock, color: 'blue', desc: 'Reschedule downstream appointments with compliance flags and priority' },
  { id: 'insurance_agent', name: 'Insurance', icon: DollarSign, color: 'emerald', desc: 'Itemized loss estimation with product, disposal, and disruption breakdown' },
  { id: 'triage_agent', name: 'Triage', icon: BarChart3, color: 'rose', desc: 'Multi-shipment priority ranking with enrichment from scored windows' },
  { id: 'approval_workflow', name: 'Approval', icon: Shield, color: 'red', desc: 'Human-in-the-loop approval queue for irreversible high-stakes actions' },
];

const COLOR_MAP = {
  violet: { bg: 'bg-violet-500/10', border: 'border-violet-500/20', text: 'text-violet-400' },
  cyan: { bg: 'bg-cyan-500/10', border: 'border-cyan-500/20', text: 'text-cyan-400' },
  indigo: { bg: 'bg-indigo-500/10', border: 'border-indigo-500/20', text: 'text-indigo-400' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400' },
  blue: { bg: 'bg-blue-500/10', border: 'border-blue-500/20', text: 'text-blue-400' },
  emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400' },
  rose: { bg: 'bg-rose-500/10', border: 'border-rose-500/20', text: 'text-rose-400' },
  red: { bg: 'bg-red-500/10', border: 'border-red-500/20', text: 'text-red-400' },
};

function getAgentMeta(toolId) {
  const agent = AGENTS.find(a => a.id === toolId);
  if (!agent) return { icon: Zap, color: COLOR_MAP.violet, name: toolId };
  return { icon: agent.icon, color: COLOR_MAP[agent.color], name: agent.name };
}

/* ── Shared helpers ────────────────────────────────────────────────── */

function MethodBadge({ method }) {
  if (!method) return null;
  const isLLM = String(method).includes('llm') || String(method).includes('vector');
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset ${
      isLLM ? 'bg-violet-500/15 text-violet-400 ring-violet-500/20' : 'bg-slate-700/50 text-slate-400 ring-slate-600/30'
    }`}>
      {isLLM && <Brain className="w-2.5 h-2.5" />}
      {String(method).replace(/_/g, ' ')}
    </span>
  );
}

function KV({ label, value, mono = false }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div className="flex items-start gap-1.5 text-[11px]">
      <span className="text-slate-500 shrink-0">{label}:</span>
      <span className={`text-slate-300 ${mono ? 'font-mono' : ''}`}>{String(value)}</span>
    </div>
  );
}

function safeStr(val) {
  if (val === null || val === undefined) return '';
  if (typeof val === 'object') return JSON.stringify(val);
  return String(val);
}

/* ── Per-tool structured result renderers ──────────────────────────── */

function ComplianceResult({ r }) {
  if (!r) return null;
  const cv = r.compliance_validation || {};
  const status = cv.compliance_status || r.compliance_status || 'unknown';
  const regs = cv.regulations_checked || cv.applicable_citations || [];
  const rawViolations = cv.violations || r.violations || [];
  const violations = rawViolations.map(v => typeof v === 'object' ? (v.violation_type || v.description || JSON.stringify(v)) : String(v));

  const statusColor = status === 'compliant' || status === 'pass'
    ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
    : status === 'conditional_pass'
    ? 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20'
    : 'text-red-400 bg-red-500/10 border-red-500/20';

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`px-2.5 py-1 rounded-lg text-xs font-bold border ${statusColor}`}>{status.toUpperCase()}</span>
        <MethodBadge method={cv.decision_method || r.decision_method} />
        {(cv.disposition || r.disposition) && <span className="text-[10px] text-slate-500 bg-slate-800 px-2 py-0.5 rounded">Disposition: {cv.disposition || r.disposition}</span>}
      </div>
      {violations.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/10 rounded-lg p-3">
          <p className="text-[10px] font-semibold text-red-400 uppercase tracking-wider flex items-center gap-1 mb-1"><AlertTriangle className="w-3 h-3" /> Violations ({violations.length})</p>
          {violations.slice(0, 5).map((v, i) => <p key={i} className="text-[11px] text-red-300/80 pl-4 truncate">• {v}</p>)}
          {violations.length > 5 && <p className="text-[10px] text-red-400/50 pl-4">+{violations.length - 5} more</p>}
        </div>
      )}
      {regs.length > 0 && (
        <div className="bg-violet-500/5 border border-violet-500/10 rounded-lg p-3">
          <p className="text-[10px] font-semibold text-violet-400 uppercase tracking-wider flex items-center gap-1 mb-1"><BookOpen className="w-3 h-3" /> Regulations Checked ({regs.length})</p>
          {regs.slice(0, 4).map((c, i) => <p key={i} className="text-[11px] text-violet-300/70 pl-4 truncate">• {safeStr(c)}</p>)}
          {regs.length > 4 && <p className="text-[10px] text-violet-400/50 pl-4">+{regs.length - 4} more</p>}
        </div>
      )}
      {cv.evidence_summary && <p className="text-[11px] text-slate-400 italic leading-relaxed">{safeStr(cv.evidence_summary)}</p>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Score" value={cv.compliance_score} mono />
        <KV label="Risk Tier" value={cv.risk_tier} />
        <KV label="Event" value={cv.event_type} />
        <KV label="Log ID" value={r.log_id} mono />
      </div>
    </div>
  );
}

function RouteResult({ r }) {
  if (!r) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-bold text-white">{safeStr(r.carrier) || '—'}</span>
        <MethodBadge method={r.selection_method} />
        {r.temp_class && <span className="text-[10px] bg-cyan-500/10 text-cyan-400 px-2 py-0.5 rounded border border-cyan-500/20">{r.temp_class}</span>}
      </div>
      {r.recommended_route && <p className="text-xs text-slate-400">{safeStr(r.recommended_route)}</p>}
      {r.selection_rationale && (
        <div className="bg-violet-500/5 border border-violet-500/10 rounded-lg p-3">
          <p className="text-[10px] font-semibold text-violet-400 uppercase tracking-wider mb-1 flex items-center gap-1"><Brain className="w-3 h-3" /> LLM Rationale</p>
          <p className="text-[11px] text-violet-300/80 leading-relaxed">{safeStr(r.selection_rationale)}</p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="ETA change" value={r.eta_change_hours != null ? `${r.eta_change_hours}h` : null} />
        <KV label="Reason" value={r.reason} />
      </div>
    </div>
  );
}

function ColdStorageResult({ r }) {
  if (!r) return null;
  const alts = Array.isArray(r.alternative_facilities) ? r.alternative_facilities : [];
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-semibold text-white">{safeStr(r.recommended_facility) || '—'}</span>
        {r.suitability_tier && <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase bg-emerald-500/15 text-emerald-400 ring-1 ring-inset ring-emerald-500/20">{r.suitability_tier}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Location" value={r.location} />
        <KV label="Temp range" value={r.temp_range_supported || r.temp_range} mono />
        <KV label="Capacity" value={r.available_capacity_pct != null ? `${Number(r.available_capacity_pct).toFixed(0)}%` : null} />
        <KV label="Advance notice" value={r.advance_notice_required_hours != null ? `${r.advance_notice_required_hours}h` : null} />
        <KV label="Contact" value={r.contact} />
        <KV label="Urgency" value={r.urgency} />
      </div>
      {alts.length > 0 && (
        <div className="mt-1">
          <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-1">Alternatives ({alts.length})</p>
          {alts.slice(0, 3).map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-[11px] py-0.5">
              <span className="text-slate-400 truncate flex-1">{safeStr(a.name || a.id || `Alt ${i + 1}`)}</span>
              {a.disqualified ? <span className="text-red-400 text-[10px]">{safeStr(a.disqualification_reason).replace(/_/g, ' ')}</span>
                : a.suitability_tier && <span className="text-emerald-400 text-[10px]">{a.suitability_tier}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InsuranceResult({ r }) {
  if (!r) return null;
  const lb = r.loss_breakdown && typeof r.loss_breakdown === 'object' ? r.loss_breakdown : {};
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-lg font-bold text-white">{r.estimated_loss_usd != null ? `$${Number(r.estimated_loss_usd).toLocaleString()}` : '—'}</span>
        <span className="text-[10px] text-slate-500">estimated loss</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Product" value={r.product_name} />
        <KV label="Incident" value={r.incident_summary} />
        {Object.keys(lb).length > 0 && Object.entries(lb).map(([k, v]) => <KV key={k} label={k.replace(/_/g, ' ')} value={typeof v === 'number' ? `$${v.toLocaleString()}` : safeStr(v)} />)}
        <KV label="Replacement" value={r.replacement_lead_time_days != null ? `${r.replacement_lead_time_days}d (${r.expedited_lead_time_days || '?'}d exp.)` : null} />
        <KV label="Substitute" value={r.substitute_available != null ? (r.substitute_available ? 'Available' : 'No') : null} />
      </div>
      {Array.isArray(r.next_steps) && r.next_steps.length > 0 && (
        <div className="mt-1">
          <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-1">Next Steps</p>
          {r.next_steps.slice(0, 3).map((s, i) => <p key={i} className="text-[10px] text-slate-400 pl-3">• {safeStr(s)}</p>)}
        </div>
      )}
    </div>
  );
}

function SchedulingResult({ r }) {
  if (!r) return null;
  const recs = Array.isArray(r.facility_recommendations) ? r.facility_recommendations : [];
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Reason" value={r.reason} />
        <KV label="Product" value={r.product_id} />
      </div>
      {recs.length > 0 && (
        <div className="space-y-2 mt-1">
          {recs.slice(0, 2).map((f, i) => (
            <div key={i} className="bg-white/[0.02] border border-white/[0.04] rounded-lg p-2.5 space-y-1">
              <p className="text-[11px] text-white font-medium truncate">{safeStr(f.facility)}</p>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                <KV label="Action" value={f.action?.replace(/_/g, ' ')} />
                <KV label="Appointments" value={f.appointment_count} />
                <KV label="Revised ETA" value={f.revised_eta} mono />
                <KV label="Patient impact" value={f.patient_impact} />
                <KV label="Contact" value={f.facility_contact} mono />
              </div>
            </div>
          ))}
          {recs.length > 2 && <p className="text-[10px] text-slate-500">+{recs.length - 2} more facilities</p>}
        </div>
      )}
    </div>
  );
}

function NotificationResult({ r }) {
  if (!r) return null;
  const ap = r.alert_payload || {};
  const isAgentic = r.agentic_workflow === true;
  const sent = r.notifications_sent || [];

  const msgPreview = r.message_preview || ap.message || r.message || '';

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Channel" value={r.channel} />
        <KV label="Recipients" value={Array.isArray(r.recipients) ? r.recipients.join(', ') : safeStr(r.recipients)} />
        {isAgentic && <KV label="Batch ID" value={r.notification_batch_id} mono />}
        {isAgentic && <KV label="Sent/Failed" value={`${r.successful_deliveries || 0} / ${r.failed_deliveries || 0}`} />}
        {!isAgentic && <KV label="Revised ETA" value={ap.revised_eta} mono />}
        {!isAgentic && <KV label="Spoilage" value={ap.spoilage_probability_pct != null ? `${ap.spoilage_probability_pct}%` : null} />}
      </div>

      {msgPreview && (
        <div className="mt-1.5 p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/15">
          <span className="text-[9px] font-semibold text-amber-400 uppercase tracking-wider block mb-1">Notification Message</span>
          <p className="text-xs text-amber-200/90 leading-relaxed whitespace-pre-wrap">{msgPreview}</p>
        </div>
      )}

      {sent.length > 0 && (
        <div className="space-y-1">
          <span className="text-[9px] font-semibold text-cyan-400 uppercase tracking-wider">Delivered Notifications</span>
          {sent.slice(0, 4).map((n, i) => (
            <div key={i} className="flex items-center gap-2 text-[11px] p-1.5 rounded bg-slate-800/40">
              <span className={`w-1.5 h-1.5 rounded-full ${n.status === 'sent' ? 'bg-emerald-400' : 'bg-red-400'}`} />
              <span className="text-slate-300 font-medium">{n.recipient_name || n.recipient_role}</span>
              <span className="text-slate-500">via {n.channel}</span>
              {n.subject && <span className="text-cyan-300/80 truncate ml-auto max-w-[200px]">"{n.subject}"</span>}
            </div>
          ))}
          {sent.length > 4 && <p className="text-[10px] text-slate-500">+{sent.length - 4} more</p>}
        </div>
      )}
    </div>
  );
}

function ApprovalResult({ r, decisionMeta }) {
  if (!r) return null;
  const isResolved = decisionMeta?._approval_status === 'approved' || decisionMeta?._execution_mode === 'post_approval';
  const displayStatus = isResolved ? 'approved' : (r.status || 'pending');
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
          displayStatus === 'approved' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
          : displayStatus === 'rejected' ? 'bg-red-500/10 text-red-400 border-red-500/20'
          : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
        }`}>{displayStatus.toUpperCase()}</span>
        {decisionMeta?._approved_by && <span className="text-[10px] text-slate-500">by {decisionMeta._approved_by}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV label="Approval ID" value={r.approval_id} mono />
        <KV label="Urgency" value={r.urgency} />
        {r.message && <div className="col-span-2"><KV label="Message" value={r.message} /></div>}
      </div>
    </div>
  );
}

function ToolResult({ tool, result: r, decisionMeta }) {
  if (!r) return null;
  try {
    switch (tool) {
      case 'compliance_agent':   return <ComplianceResult r={r} />;
      case 'route_agent':        return <RouteResult r={r} />;
      case 'cold_storage_agent': return <ColdStorageResult r={r} />;
      case 'scheduling_agent':   return <SchedulingResult r={r} />;
      case 'insurance_agent':    return <InsuranceResult r={r} />;
      case 'notification_agent': return <NotificationResult r={r} />;
      case 'approval_workflow':  return <ApprovalResult r={r} decisionMeta={decisionMeta} />;
      default: return <FallbackResult r={r} />;
    }
  } catch {
    return <FallbackResult r={r} />;
  }
}

function FallbackResult({ r }) {
  if (!r) return null;
  const show = ['status', 'risk_tier', 'message', 'shipment_id'];
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
      {show.filter(k => r[k]).map(k => <KV key={k} label={k} value={safeStr(r[k])} />)}
    </div>
  );
}

/* ── Agent Registry (no type labels) ──────────────────────────────── */

function AgentRegistry() {
  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 mb-3">Agent Tool Registry</h2>
      <div className="grid grid-cols-4 gap-3">
        {AGENTS.map((agent, i) => {
          const c = COLOR_MAP[agent.color];
          const Icon = agent.icon;
          return (
            <div key={agent.id} className={`glass-card-sm p-4 animate-slide-up border ${c.border}`} style={{ animationDelay: `${i * 50}ms` }}>
              <div className="flex items-center gap-2 mb-2">
                <div className={`rounded-lg p-1.5 ${c.bg}`}><Icon className={`w-4 h-4 ${c.text}`} /></div>
                <span className={`text-xs font-bold ${c.text}`}>{agent.name}</span>
              </div>
              <p className="text-[10px] text-slate-400 leading-relaxed">{agent.desc}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Pipeline Step Visualizer ──────────────────────────────────────── */

function PipelineSteps({ decision }) {
  const d = decision || {};
  const isPostApproval = d._execution_mode === 'post_approval' || d._execution_mode === 'human_selective';
  const isConfirmed = d._execution_mode === 'confirmed' || d.review_status === 'confirmed';
  const isAwaitingReview = d.awaiting_approval && !isPostApproval && !isConfirmed;
  const hasRevisedPlan = Array.isArray(d.revised_plan) && d.revised_plan.length > 0;
  const hasCorrections = d.review_status === 'corrections_proposed';
  const hasReflection = Array.isArray(d.reflection_notes) && d.reflection_notes.length > 0;
  const hasObservation = !!d.observation;
  const hasExecution = Array.isArray(d.actions_taken) && d.actions_taken.length > 0;

  const steps = isPostApproval ? [
    { label: 'Interpret', done: true, icon: Activity },
    { label: 'Plan', done: true, icon: Brain },
    { label: 'Execute', done: true, icon: Play },
    { label: 'Observe', done: true, icon: Eye },
    { label: 'Reflect', done: true, icon: Cpu },
    ...(hasRevisedPlan ? [{ label: 'Revise', done: true, icon: Zap }] : []),
    { label: 'Reviewed', done: true, icon: Shield, special: true },
    { label: 'Re-Execute', done: true, icon: RotateCcw },
    { label: 'Output', done: !!d.decision_summary, icon: CheckCircle },
  ] : isConfirmed ? [
    { label: 'Interpret', done: true, icon: Activity },
    { label: 'Plan', done: true, icon: Brain },
    { label: 'Execute', done: true, icon: Play },
    { label: 'Observe', done: true, icon: Eye },
    { label: 'Reflect', done: true, icon: Cpu },
    { label: 'Confirmed', done: true, icon: Shield, special: true },
    { label: 'Output', done: true, icon: CheckCircle },
  ] : isAwaitingReview ? [
    { label: 'Interpret', done: true, icon: Activity },
    { label: 'Plan', done: true, icon: Brain },
    { label: 'Execute', done: hasExecution, icon: Play },
    { label: 'Observe', done: hasObservation, icon: Eye },
    { label: 'Reflect', done: hasReflection, icon: Cpu },
    ...(hasRevisedPlan ? [{ label: 'Revise', done: true, icon: Zap }] : []),
    { label: 'Human Review', done: false, icon: Shield, special: true, pulse: true },
    { label: 'Output', done: false, icon: CheckCircle },
  ] : [
    { label: 'Interpret', done: true, icon: Activity },
    { label: 'Plan', done: Array.isArray(d.draft_plan) && d.draft_plan.length > 0, icon: Brain },
    { label: 'Execute', done: hasExecution, icon: Play },
    { label: 'Observe', done: hasObservation, icon: Eye },
    { label: 'Reflect', done: hasReflection, icon: Cpu },
    ...(hasRevisedPlan ? [{ label: 'Revise', done: true, icon: Zap }] : []),
    { label: 'Output', done: !!d.decision_summary, icon: CheckCircle },
  ];
  return (
    <div className="flex items-center gap-1 overflow-x-auto py-2">
      {steps.map((s, i) => {
        const Icon = s.icon;
        const isReplan = s.label.startsWith('Re-plan');
        return (
          <div key={s.label} className="flex items-center gap-1 shrink-0">
            <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold ${
              isReplan ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : s.special && s.pulse ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse'
                : s.special ? 'bg-violet-500/10 text-violet-400 border border-violet-500/20'
                : s.done ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                : 'bg-white/[0.03] text-slate-600 border border-white/[0.06]'
            }`}>
              <Icon className="w-3 h-3" /> {s.label}
            </div>
            {i < steps.length - 1 && <ArrowRight className={`w-3 h-3 shrink-0 ${s.done ? 'text-cyan-600' : 'text-slate-700'}`} />}
          </div>
        );
      })}
    </div>
  );
}

/* ── Main Component ───────────────────────────────────────────────── */

export default function AgentActivity() {
  const { data: history, loading, refetch } = useApi('/orchestrator/history?limit=30');
  const { data: mode } = useApi('/orchestrator/mode');
  const { messages: wsMessages, connected: wsConnected } = useWebSocket([
    'orchestrator_decision', 'approval_decided', 'approval_executed', 'tool_executed',
  ]);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [windowId, setWindowId] = useState('');
  const [demoResult, setDemoResult] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);

  useEffect(() => {
    if (wsMessages.length === 0) return;
    const latest = wsMessages[wsMessages.length - 1];
    setLiveEvents(prev => [...prev.slice(-19), { ...latest, _ts: Date.now() }]);

    if (latest.type === 'orchestrator_decision' || latest.type === 'approval_executed') {
      refetch();
    }
  }, [wsMessages, refetch]);

  const runSingle = useCallback(async (wid) => {
    setRunning(true);
    setDemoResult(null);
    try {
      const result = await postApi(`/orchestrator/run/${wid}`, {});
      if (result && !result.detail) setDemoResult(result);
      else setDemoResult({ error: result?.detail || 'Unknown error' });
      await refetch();
    } catch (e) {
      setDemoResult({ error: e.message });
    } finally { setRunning(false); }
  }, [refetch]);

  const runCriticalBatch = useCallback(async () => {
    setRunning(true);
    try {
      const windows = await getApi('/windows?risk_tier=CRITICAL&limit=5');
      if (Array.isArray(windows) && windows.length > 0) {
        await postApi('/orchestrator/run-batch', windows.map(w => w.window_id));
        await refetch();
      }
    } catch (e) {
      setDemoResult({ error: e.message });
    } finally { setRunning(false); }
  }, [refetch]);

  const runDemo = useCallback(async () => {
    setRunning(true);
    setDemoResult(null);
    try {
      const windows = await getApi('/windows?risk_tier=CRITICAL&limit=1');
      if (Array.isArray(windows) && windows.length > 0) {
        const result = await postApi(`/orchestrator/run/${windows[0].window_id}`, {});
        if (result && !result.detail) setDemoResult(result);
        else setDemoResult({ error: result?.detail || 'Unknown error' });
        await refetch();
      }
    } catch (e) {
      setDemoResult({ error: e.message });
    } finally { setRunning(false); }
  }, [refetch]);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Agent Orchestration</h1>
          <p className="text-sm text-slate-500 mt-0.5">Plan → Reflect → Revise → Execute → Observe pipeline</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="glass-card-sm px-2.5 py-1.5 flex items-center gap-1.5">
            {wsConnected ? <Wifi className="w-3 h-3 text-emerald-400" /> : <WifiOff className="w-3 h-3 text-red-400" />}
            <span className={`text-[10px] font-medium ${wsConnected ? 'text-emerald-400' : 'text-red-400'}`}>
              {wsConnected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          {mode && (
            <div className="glass-card-sm px-3 py-2 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-violet-400" />
              <span className="text-[11px] text-violet-300 font-mono">{safeStr(mode.model || 'deterministic')}</span>
              <span className={`w-2 h-2 rounded-full ${mode.mode === 'agentic' ? 'bg-emerald-400' : 'bg-slate-500'}`} />
            </div>
          )}
        </div>
      </div>

      {/* Live Event Feed */}
      {liveEvents.length > 0 && (
        <div className="glass-card-sm p-3 border border-cyan-500/10 space-y-1.5 max-h-32 overflow-y-auto scrollbar-thin">
          <div className="flex items-center gap-1.5 mb-1">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">Live Events</span>
          </div>
          {liveEvents.slice(-5).reverse().map((evt, i) => (
            <div key={i} className="flex items-center gap-2 text-[11px]">
              <span className="text-slate-600 font-mono w-16 shrink-0">{new Date(evt._ts).toLocaleTimeString()}</span>
              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                evt.type === 'approval_executed' ? 'bg-emerald-500/10 text-emerald-400'
                : evt.type === 'approval_decided' ? 'bg-amber-500/10 text-amber-400'
                : 'bg-cyan-500/10 text-cyan-400'
              }`}>{evt.type.replace('_', ' ')}</span>
              <span className="text-slate-400 truncate">
                {evt.decision?.window_id || evt.decision?._window_id || evt.result?.approval_id || evt.approval_id || ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Run Panel */}
      <div className="glass-card p-5 space-y-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2 flex-1 min-w-[300px]">
            <span className="text-sm text-slate-400 font-medium shrink-0">Window ID:</span>
            <input value={windowId} onChange={e => setWindowId(e.target.value)}
              placeholder="e.g. W00464"
              className="bg-slate-800/60 border border-white/[0.08] rounded-lg px-3 py-2 text-sm w-36 text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500/40 focus:ring-1 focus:ring-cyan-500/20 transition" />
            <button onClick={() => windowId && runSingle(windowId)} disabled={running || !windowId}
              className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-lg text-sm font-medium hover:from-cyan-500 hover:to-blue-500 disabled:opacity-50 transition-all shadow-lg shadow-cyan-500/15">
              <Play className="w-3.5 h-3.5" /> Run
            </button>
          </div>
          <button onClick={runDemo} disabled={running}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-lg text-sm font-medium hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-500/15">
            <Bot className="w-4 h-4" /> {running ? 'Running...' : 'Run Live Demo'}
          </button>
          <button onClick={runCriticalBatch} disabled={running}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-red-600 to-rose-600 text-white rounded-lg text-sm font-medium hover:from-red-500 hover:to-rose-500 disabled:opacity-50 transition-all shadow-lg shadow-red-500/15">
            <Zap className="w-4 h-4" /> Batch Top 5
          </button>
        </div>
        {running && (
          <div className="flex items-center gap-3 text-cyan-400 animate-pulse">
            <div className="w-4 h-4 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
            <span className="text-sm">Orchestrating — LLM planning, reflecting, executing, observing...</span>
          </div>
        )}
      </div>

      {/* Demo Result */}
      {demoResult && !demoResult.error && (
        <div className="glass-card overflow-hidden animate-slide-up gradient-border">
          <div className="px-5 py-3.5 border-b border-white/[0.06] flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-white">Latest Result</span>
            <TierBadge tier={demoResult.risk_tier} />
            <span className="text-xs text-slate-500 font-mono ml-auto">{safeStr(demoResult.window_id || demoResult._window_id)}</span>
          </div>
          <div className="px-5 py-4 space-y-4">
            <PipelineSteps decision={demoResult} />
            {demoResult.decision_summary && <p className="text-sm text-slate-300">{safeStr(demoResult.decision_summary)}</p>}
            <ObservationPanel decision={demoResult} />
            {renderActions(demoResult.actions_taken, demoResult)}
          </div>
        </div>
      )}

      {demoResult?.error && (
        <div className="glass-card-sm p-4 border border-red-500/20 bg-red-500/5">
          <p className="text-sm text-red-400">Error: {safeStr(demoResult.error)}</p>
        </div>
      )}

      <AgentRegistry />

      {/* History */}
      {loading && (
        <div className="flex items-center gap-3 text-slate-500 py-4">
          <div className="w-5 h-5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
          Loading history...
        </div>
      )}

      {Array.isArray(history) && history.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300">Orchestration History ({history.length})</h2>
            <div className="flex items-center gap-2">
              <button onClick={refetch} className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition">
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
              <button onClick={async () => {
                await deleteApi('/orchestrator/history');
                await refetch();
                setDemoResult(null);
              }} className="flex items-center gap-1.5 text-xs text-red-500/70 hover:text-red-400 transition">
                <XCircle className="w-3 h-3" /> Clear
              </button>
            </div>
          </div>
          {history.map((dec, i) => (
            <DecisionCard key={`${dec.window_id || dec._window_id}-${i}`} decision={dec}
              expanded={expanded === i} onToggle={() => setExpanded(expanded === i ? null : i)} />
          ))}
        </div>
      )}
    </div>
  );
}

function ObservationPanel({ decision }) {
  const d = decision || {};
  if (!d.observation) return null;

  const adequate = !d.observation_issues?.length;
  return (
    <div className={`rounded-xl p-4 border ${
      adequate ? 'bg-emerald-500/5 border-emerald-500/10' : 'bg-amber-500/5 border-amber-500/10'
    }`}>
      <div className="flex items-center gap-2 mb-2">
        <Eye className={`w-4 h-4 ${adequate ? 'text-emerald-400' : 'text-amber-400'}`} />
        <span className={`text-xs font-bold ${adequate ? 'text-emerald-400' : 'text-amber-400'}`}>
          Post-Execution Observation
        </span>
        {d.replan_count > 0 && (
          <span className="flex items-center gap-1 text-[10px] text-amber-300 bg-amber-500/10 px-2 py-0.5 rounded-full">
            <RotateCcw className="w-2.5 h-2.5" /> Re-planned {d.replan_count}x
          </span>
        )}
      </div>
      <p className={`text-[11px] leading-relaxed ${adequate ? 'text-emerald-300/70' : 'text-amber-300/70'}`}>
        {safeStr(d.observation)}
      </p>
      {Array.isArray(d.observation_issues) && d.observation_issues.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {d.observation_issues.map((issue, i) => (
            <p key={i} className="text-[10px] text-amber-400/80 pl-3">- {safeStr(issue)}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function renderActions(actionsTaken, decisionMeta) {
  if (!Array.isArray(actionsTaken) || actionsTaken.length === 0) return null;

  const firstPass = actionsTaken.filter(a => a?._pass === 'first_pass');
  const postApproval = actionsTaken.filter(a => a?._pass === 'post_approval');
  const ungrouped = actionsTaken.filter(a => !a?._pass);
  const hasBothPasses = firstPass.length > 0 && postApproval.length > 0;

  const renderGroup = (items, label, labelColor) => (
    <>
      {label && (
        <div className="col-span-2 flex items-center gap-2 pt-1">
          <div className="h-px flex-1 bg-white/[0.06]" />
          <span className={`text-[10px] font-bold uppercase tracking-wider ${labelColor}`}>{label}</span>
          <div className="h-px flex-1 bg-white/[0.06]" />
        </div>
      )}
      {items.map((a, j) => {
        if (!a || typeof a !== 'object') return null;
        const meta = getAgentMeta(a.tool);
        const Icon = meta.icon;
        return (
          <div key={`${label}-${j}`} className={`rounded-xl p-4 border ${meta.color.border} ${meta.color.bg}`}>
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`w-4 h-4 ${meta.color.text}`} />
              <span className={`text-xs font-bold ${meta.color.text}`}>{meta.name}</span>
              {a.result?.status && <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full ml-auto">{safeStr(a.result.status)}</span>}
            </div>
            <ToolResult tool={a.tool} result={a.result} decisionMeta={decisionMeta} />
          </div>
        );
      })}
    </>
  );

  return (
    <div className="grid grid-cols-2 gap-3">
      {hasBothPasses ? (
        <>
          {renderGroup(firstPass, `First Pass — ${firstPass.length} tools`, 'text-slate-500')}
          {renderGroup(postApproval, `Post-Approval — ${postApproval.length} tools`, 'text-violet-400')}
        </>
      ) : (
        renderGroup(ungrouped.length > 0 ? ungrouped : actionsTaken, null, null)
      )}
    </div>
  );
}

/* ── Decision Card ─────────────────────────────────────────────────── */

function DecisionCard({ decision, expanded, onToggle }) {
  const d = decision || {};
  const actionsCount = Array.isArray(d.actions_taken) ? d.actions_taken.length : 0;
  const isPostApproval = d._execution_mode === 'post_approval';
  const isConfirmed = d._execution_mode === 'confirmed' || d.review_status === 'confirmed';
  const isAwaitingApproval = d.awaiting_approval && !isPostApproval && !isConfirmed;
  const hasCorrections = d.review_status === 'corrections_proposed';

  return (
    <div className={`glass-card overflow-hidden ${
      isPostApproval ? 'ring-1 ring-emerald-500/20'
      : isAwaitingApproval ? 'ring-1 ring-amber-500/20'
      : ''
    }`}>
      <div role="button" tabIndex={0} className="px-5 py-3.5 flex items-center gap-3 cursor-pointer hover:bg-white/[0.02] transition" onClick={onToggle} onKeyDown={e => e.key === 'Enter' && onToggle()}>
        <TierBadge tier={d.risk_tier || 'LOW'} />
        <div className="min-w-0">
          <span className="font-mono text-sm font-semibold text-white">{safeStr(d.window_id || d._window_id)}</span>
          <span className="text-xs text-slate-500 ml-2">{safeStr(d.shipment_id)} / {safeStr(d.container_id)}</span>
        </div>
        <div className="ml-auto flex items-center gap-3 shrink-0">
          {actionsCount > 0 && <span className="flex items-center gap-1 text-xs text-emerald-400"><CheckCircle className="w-3.5 h-3.5" />{actionsCount} tools</span>}

          {isPostApproval && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-violet-500/10 text-violet-400 border border-violet-500/20">
              <CheckCircle className="w-3 h-3" /> Reviewed & Re-Executed
            </span>
          )}
          {isConfirmed && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <CheckCircle className="w-3 h-3" /> Human Confirmed
            </span>
          )}
          {isAwaitingApproval && hasCorrections && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Shield className="w-3 h-3" /> Corrections Proposed — Awaiting Review
            </span>
          )}
          {isAwaitingApproval && !hasCorrections && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Shield className="w-3 h-3" /> Execution Complete — Awaiting Confirmation
            </span>
          )}

          <span className="font-mono text-xs text-slate-500">conf {Number(d.confidence || 0).toFixed(2)}</span>
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-600" /> : <ChevronDown className="w-4 h-4 text-slate-600" />}
        </div>
      </div>

      {expanded && (
        <div className="px-5 pb-5 pt-2 border-t border-white/[0.06] space-y-4 animate-fade-in">
          {isPostApproval && d._approved_by && (
            <div className="flex items-center gap-2 text-[11px] bg-emerald-500/5 border border-emerald-500/10 rounded-lg px-3 py-2">
              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400 font-medium">
                Approved by {safeStr(d._approved_by)}
                {d._approved_at && <span className="text-emerald-400/50 ml-1">at {new Date(d._approved_at).toLocaleString()}</span>}
                {' '}&mdash; tools executed after human approval
              </span>
            </div>
          )}
          {isAwaitingApproval && hasCorrections && (
            <div className="bg-amber-500/5 border border-amber-500/10 rounded-lg px-3 py-2 space-y-2">
              <div className="flex items-center gap-2 text-[11px]">
                <Shield className="w-3.5 h-3.5 text-amber-400" />
                <span className="text-amber-400 font-medium">
                  Tools executed. Post-execution reflection found gaps — corrective actions proposed. Go to Review Queue to approve, modify, or dismiss.
                </span>
              </div>
              {Array.isArray(d.proposed_tools) && d.proposed_tools.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  <span className="text-[10px] text-slate-500 mr-1">Proposed corrections:</span>
                  {d.proposed_tools.map(t => (
                    <span key={t} className="bg-amber-500/10 text-amber-400 text-[10px] px-2 py-0.5 rounded border border-amber-500/15">{t}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          {isAwaitingApproval && !hasCorrections && (
            <div className="bg-emerald-500/5 border border-emerald-500/10 rounded-lg px-3 py-2">
              <div className="flex items-center gap-2 text-[11px]">
                <Shield className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-emerald-400 font-medium">
                  All tools executed successfully. Reflection found no gaps. Go to Review Queue to confirm or add additional tools.
                </span>
              </div>
            </div>
          )}

          <PipelineSteps decision={d} />
          {d.decision_summary && <p className="text-sm text-slate-300">{safeStr(d.decision_summary)}</p>}

          {d.llm_reasoning && (
            <div className="bg-violet-500/5 border border-violet-500/10 rounded-xl p-4">
              <p className="text-[10px] font-semibold text-violet-400 uppercase tracking-wider mb-1.5 flex items-center gap-1"><Brain className="w-3 h-3" /> LLM Reasoning</p>
              <p className="text-[11px] text-violet-300/70 leading-relaxed whitespace-pre-line">{safeStr(d.llm_reasoning)}</p>
            </div>
          )}

          {Array.isArray(d.draft_plan) && d.draft_plan.length > 0 && <PlanSection title="Draft Plan" steps={d.draft_plan} />}
          {Array.isArray(d.reflection_notes) && d.reflection_notes.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Reflection</p>
              {d.reflection_notes.map((n, j) => (
                <p key={j} className={`text-xs ${
                  String(n).includes('GAP') ? 'text-amber-400/80'
                  : String(n).includes('QUALITY') ? 'text-cyan-400/80'
                  : 'text-emerald-400/70'
                }`}>{safeStr(n)}</p>
              ))}
            </div>
          )}
          {Array.isArray(d.revised_plan) && d.revised_plan.length > 0 && (
            <PlanSection
              title="Revised Plan (from reflection)"
              steps={d.revised_plan}
              postApprovalTools={isPostApproval ? (d.post_approval_actions || []).map(a => a?.tool).filter(Boolean) : null}
            />
          )}

          {actionsCount > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
                {isPostApproval ? 'All Tool Execution Results' : Array.isArray(d.corrective_actions) && d.corrective_actions.length > 0 ? 'First-Pass Execution Results' : 'Tool Execution Results'}
              </p>
              {renderActions(d.actions_taken, d)}
            </div>
          )}

          {Array.isArray(d.corrective_actions) && d.corrective_actions.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-amber-400/80 uppercase tracking-wider mb-3 flex items-center gap-1">
                <RotateCcw className="w-3 h-3" /> Corrective Execution Results
              </p>
              {renderActions(d.corrective_actions, d)}
            </div>
          )}

          <ObservationPanel decision={d} />
        </div>
      )}
    </div>
  );
}

function PlanSection({ title, steps, postApprovalTools }) {
  if (!Array.isArray(steps)) return null;
  const isDeferred = (s) => {
    const act = String(s?.action || '').toLowerCase();
    const tool = String(s?.tool || '').toLowerCase();
    return act.includes('deferred') || (tool === 'notification_agent' && act.includes('notification'));
  };
  return (
    <div>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</p>
      <div className="space-y-1.5">
        {steps.map((s, i) => {
          if (!s || typeof s !== 'object') return null;
          const deferred = isDeferred(s);
          return (
            <div key={i} className={`flex gap-3 text-xs items-start ${deferred ? 'pl-2 border-l-2 border-violet-500/30' : ''}`}>
              <span className={`font-mono w-5 text-right shrink-0 pt-0.5 ${deferred ? 'text-violet-500' : 'text-slate-600'}`}>{s.step ?? i + 1}.</span>
              <div className="min-w-0">
                <span className={deferred ? 'text-violet-300' : 'text-slate-300'}>{safeStr(s.action)}</span>
                {s.tool && <span className={`ml-2 font-mono text-[10px] ${deferred ? 'text-violet-400/70' : 'text-cyan-500/70'}`}>[{s.tool}]</span>}
                {deferred && <span className="ml-2 text-[9px] bg-violet-500/10 text-violet-400 px-1.5 py-0.5 rounded border border-violet-500/20">⏳ awaits approval</span>}
                {s.reason && <p className={`text-[10px] mt-0.5 truncate ${deferred ? 'text-violet-500/60' : 'text-slate-600'}`}>{safeStr(s.reason)}</p>}
              </div>
            </div>
          );
        })}
        {Array.isArray(postApprovalTools) && postApprovalTools.length > 0 && (
          <div className="mt-2 pt-2 border-t border-violet-500/15 space-y-1.5">
            <p className="text-[9px] font-semibold text-violet-400 uppercase tracking-wider flex items-center gap-1"><CheckCircle className="w-2.5 h-2.5" /> Executed after human approval</p>
            {postApprovalTools.map((t, i) => (
              <div key={i} className="flex gap-3 text-xs items-start pl-2 border-l-2 border-emerald-500/30">
                <span className="font-mono text-emerald-500 w-5 text-right shrink-0 pt-0.5">✓</span>
                <div className="min-w-0">
                  <span className="text-emerald-300">Executed {safeStr(t)}</span>
                  <span className="ml-2 text-emerald-400/70 font-mono text-[10px]">[{t}]</span>
                  <span className="ml-2 text-[9px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded border border-emerald-500/20">✓ approved</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
