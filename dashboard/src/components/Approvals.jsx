import { useState, useCallback, useEffect } from 'react';
import { useApi, postApi, deleteApi } from '../hooks/useApi';
import { useWebSocket } from '../hooks/useWebSocket';
import TierBadge from './TierBadge';
import {
  CheckCircle, XCircle, Shield, ArrowRight, Play, Zap, RefreshCw,
  Wifi, WifiOff, Clock, Ban,
} from 'lucide-react';

const ALL_TOOLS = [
  { id: 'compliance_agent', label: 'Compliance' },
  { id: 'route_agent', label: 'Route' },
  { id: 'cold_storage_agent', label: 'Cold Storage' },
  { id: 'notification_agent', label: 'Notification' },
  { id: 'scheduling_agent', label: 'Scheduling' },
  { id: 'insurance_agent', label: 'Insurance' },
  { id: 'triage_agent', label: 'Triage' },
];

const STATUS_STYLES = {
  pending: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20', icon: Clock, label: 'PENDING' },
  approved: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20', icon: CheckCircle, label: 'APPROVED' },
  executed: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/20', icon: Zap, label: 'EXECUTED' },
  rejected: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/20', icon: Ban, label: 'REJECTED' },
};

export default function Approvals() {
  const { data, loading, error, refetch } = useApi('/approvals/all');
  const { messages: wsMessages, connected } = useWebSocket(['approval_decided', 'approval_executed']);
  const [actionInFlight, setActionInFlight] = useState(null);
  const [selectedTools, setSelectedTools] = useState({});
  const [executionResults, setExecutionResults] = useState({});
  const [executing, setExecuting] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (wsMessages.length > 0) refetch();
  }, [wsMessages, refetch]);

  const handleDecide = useCallback(async (id, decision, proposedActions) => {
    setActionInFlight(id);
    try {
      const result = await postApi(`/approvals/${id}/decide`, { decision, decided_by: 'operator' });
      if (result?.error) {
        console.error('Decide failed:', result.error);
      }
      if (decision === 'approved' && Array.isArray(proposedActions)) {
        const validTools = ALL_TOOLS.map(t => t.id);
        const preSelected = proposedActions.filter(t => validTools.includes(t) && t !== 'approval_workflow');
        if (preSelected.length > 0) {
          setSelectedTools(prev => ({ ...prev, [id]: preSelected }));
        }
      }
      await refetch();
    } catch (e) {
      console.error('Decide error:', e);
    } finally {
      setActionInFlight(null);
    }
  }, [refetch]);

  const handleExecute = useCallback(async (approvalId) => {
    setExecuting(approvalId);
    try {
      const tools = selectedTools[approvalId];
      const body = tools && tools.length > 0 ? { selected_tools: tools } : {};
      const result = await postApi(`/approvals/${approvalId}/execute`, body);
      setExecutionResults(prev => ({ ...prev, [approvalId]: result }));
    } catch (e) {
      setExecutionResults(prev => ({ ...prev, [approvalId]: { error: e.message } }));
    } finally {
      setExecuting(null);
      setTimeout(() => refetch(), 300);
    }
  }, [selectedTools, refetch]);

  const handleClearAll = useCallback(async () => {
    try {
      await deleteApi('/approvals');
      setExecutionResults({});
      setSelectedTools({});
      await refetch();
    } catch (e) {
      console.error('Clear failed:', e);
    }
  }, [refetch]);

  const toggleTool = useCallback((approvalId, toolId) => {
    setSelectedTools(prev => {
      const current = prev[approvalId] || [];
      const next = current.includes(toolId)
        ? current.filter(t => t !== toolId)
        : [...current, toolId];
      return { ...prev, [approvalId]: next };
    });
  }, []);

  const filtered = Array.isArray(data)
    ? (filter === 'all' ? data : data.filter(a => a.status === filter))
    : [];

  const counts = Array.isArray(data) ? {
    all: data.length,
    pending: data.filter(a => a.status === 'pending').length,
    approved: data.filter(a => a.status === 'approved').length,
    executed: data.filter(a => a.status === 'executed').length,
    rejected: data.filter(a => a.status === 'rejected').length,
  } : { all: 0, pending: 0, approved: 0, executed: 0, rejected: 0 };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Approvals</h1>
          <p className="text-sm text-slate-500 mt-0.5">Human-in-the-loop approval queue — approve, select tools, execute</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="glass-card-sm px-2.5 py-1.5 flex items-center gap-1.5">
            {connected ? <Wifi className="w-3 h-3 text-emerald-400" /> : <WifiOff className="w-3 h-3 text-red-400" />}
            <span className={`text-[10px] font-medium ${connected ? 'text-emerald-400' : 'text-red-400'}`}>
              {connected ? 'Live' : 'Offline'}
            </span>
          </div>
          <button onClick={refetch} className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition glass-card-sm px-2.5 py-1.5">
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
          {Array.isArray(data) && data.length > 0 && (
            <button onClick={handleClearAll} className="flex items-center gap-1.5 text-xs text-red-400/70 hover:text-red-400 transition glass-card-sm px-2.5 py-1.5 border border-red-500/10 hover:border-red-500/20">
              <XCircle className="w-3 h-3" /> Clear All
            </button>
          )}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {['all', 'pending', 'approved', 'executed', 'rejected'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              filter === f
                ? 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30'
                : 'bg-white/[0.03] text-slate-500 border-white/[0.06] hover:border-white/[0.12]'
            }`}>
            {f.charAt(0).toUpperCase() + f.slice(1)} ({counts[f]})
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-3 text-slate-500 py-8">
          <div className="w-5 h-5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
          Loading approvals...
        </div>
      )}
      {error && <p className="text-red-400">Error: {error}</p>}

      {!loading && filtered.length === 0 && (
        <div className="glass-card p-10 text-center">
          <Shield className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">
            {filter === 'all' ? 'No approvals yet. Run orchestration on a CRITICAL window to generate one.'
              : `No ${filter} approvals.`}
          </p>
        </div>
      )}

      {filtered.map((a, i) => {
        const status = a.status || 'pending';
        const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
        const StatusIcon = style.icon;
        const isApproved = status === 'approved';
        const isExecuted = status === 'executed';
        const isRejected = status === 'rejected';
        const isPending = status === 'pending';
        const execResult = executionResults[a.approval_id];
        const toolsForThis = selectedTools[a.approval_id] || [];

        return (
          <div key={a.approval_id} className={`glass-card p-5 space-y-3 animate-slide-up ${isRejected ? 'opacity-60' : ''}`}
            style={{ animationDelay: `${i * 80}ms` }}>
            <div className="flex items-center gap-3 flex-wrap">
              <TierBadge tier={a.risk_tier} size="lg" />
              <span className="font-semibold text-white">{a.approval_id}</span>
              <span className="text-xs text-slate-500">
                {a.window_id || a.shipment_id}{a.container_id ? ` / ${a.container_id}` : ''}
              </span>

              {/* Status badge */}
              <span className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold border ${style.bg} ${style.text} ${style.border}`}>
                <StatusIcon className="w-3 h-3" /> {style.label}
              </span>

              {a.decided_by && (
                <span className="text-[10px] text-slate-600">
                  by {a.decided_by} {a.decided_at ? `at ${new Date(a.decided_at).toLocaleTimeString()}` : ''}
                </span>
              )}

              <span className="ml-auto text-[11px] text-slate-600">{a.created_at ? new Date(a.created_at).toLocaleString() : ''}</span>
            </div>

            <p className="text-sm text-slate-300 leading-relaxed">{a.action_description}</p>
            <p className="text-xs text-slate-500">{a.justification}</p>

            <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Proposed:</span>
              {Array.isArray(a.proposed_actions) && a.proposed_actions.map((act, j) => (
                <span key={j} className="flex items-center gap-1">
                  <span className="bg-slate-800 px-2 py-0.5 rounded text-slate-300">{act}</span>
                  {j < a.proposed_actions.length - 1 && <ArrowRight className="w-3 h-3 text-slate-600" />}
                </span>
              ))}
            </div>

            {/* Pending: show Approve / Reject buttons */}
            {isPending && (
              <div className="flex gap-3 pt-3 border-t border-white/[0.06]">
                <button onClick={() => handleDecide(a.approval_id, 'approved', a.proposed_actions)}
                  disabled={actionInFlight === a.approval_id}
                  className="flex items-center gap-1.5 px-5 py-2.5 bg-gradient-to-r from-emerald-600 to-green-600 text-white rounded-xl text-sm font-semibold hover:from-emerald-500 hover:to-green-500 disabled:opacity-50 transition-all shadow-lg shadow-emerald-500/15">
                  <CheckCircle className="w-4 h-4" /> Approve
                </button>
                <button onClick={() => handleDecide(a.approval_id, 'rejected', null)}
                  disabled={actionInFlight === a.approval_id}
                  className="flex items-center gap-1.5 px-5 py-2.5 bg-gradient-to-r from-red-600 to-rose-600 text-white rounded-xl text-sm font-semibold hover:from-red-500 hover:to-rose-500 disabled:opacity-50 transition-all shadow-lg shadow-red-500/15">
                  <XCircle className="w-4 h-4" /> Reject
                </button>
                {actionInFlight === a.approval_id && (
                  <div className="flex items-center gap-2 text-slate-500 text-xs">
                    <div className="w-3.5 h-3.5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
                    Processing...
                  </div>
                )}
              </div>
            )}

            {/* Approved (not yet executed): show tool selection + execute */}
            {isApproved && (
              <div className="pt-3 border-t border-emerald-500/10 space-y-3">
                <div>
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Select tools to execute (leave empty for all proposed tools)
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {ALL_TOOLS.map(tool => {
                      const selected = toolsForThis.includes(tool.id);
                      return (
                        <button key={tool.id} onClick={() => toggleTool(a.approval_id, tool.id)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                            selected
                              ? 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30 shadow-sm shadow-cyan-500/10'
                              : 'bg-white/[0.03] text-slate-500 border-white/[0.06] hover:border-white/[0.12]'
                          }`}>
                          {tool.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <button onClick={() => handleExecute(a.approval_id)}
                  disabled={executing === a.approval_id}
                  className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-xl text-sm font-semibold hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-500/15">
                  {executing === a.approval_id ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Executing...
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4" />
                      Execute {toolsForThis.length > 0 ? `${toolsForThis.length} selected tools` : 'all proposed tools'}
                    </>
                  )}
                </button>

                {execResult?.error && (
                  <div className="glass-card-sm p-3 border border-red-500/20 bg-red-500/5">
                    <p className="text-xs text-red-400">Error: {typeof execResult.error === 'object' ? JSON.stringify(execResult.error) : execResult.error}</p>
                  </div>
                )}
              </div>
            )}

            {/* Executed: show completion summary */}
            {isExecuted && (
              <div className="pt-3 border-t border-cyan-500/10">
                <div className="glass-card-sm p-4 border border-cyan-500/10">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap className="w-4 h-4 text-cyan-400" />
                    <span className="text-xs font-bold text-cyan-400">Execution Complete</span>
                    {a.executed_at && <span className="text-[10px] text-slate-600 ml-auto">{new Date(a.executed_at).toLocaleString()}</span>}
                  </div>
                  {Array.isArray(a.executed_tools) && a.executed_tools.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {a.executed_tools.map(t => (
                        <span key={t} className="bg-cyan-500/10 text-cyan-400 text-[10px] px-2 py-0.5 rounded border border-cyan-500/15">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Rejected: show info */}
            {isRejected && (
              <div className="pt-3 border-t border-red-500/10">
                <p className="text-xs text-red-400/70">
                  Rejected by {a.decided_by || 'operator'} — no execution will be performed.
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
