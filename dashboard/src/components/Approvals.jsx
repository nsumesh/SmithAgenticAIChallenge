import { useState, useCallback, useEffect } from 'react';
import { useApi, postApi, deleteApi } from '../hooks/useApi';
import { useWebSocket } from '../hooks/useWebSocket';
import TierBadge from './TierBadge';
import {
  CheckCircle, XCircle, Shield, ArrowRight, Play, Zap, RefreshCw,
  Wifi, WifiOff, Clock, Ban, Eye, AlertTriangle, ThumbsUp,
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
  pending:   { bg: 'bg-amber-500/10',   text: 'text-amber-400',   border: 'border-amber-500/20',   icon: Clock,       label: 'PENDING REVIEW' },
  approved:  { bg: 'bg-emerald-500/10',  text: 'text-emerald-400', border: 'border-emerald-500/20', icon: CheckCircle,  label: 'APPROVED' },
  confirmed: { bg: 'bg-cyan-500/10',     text: 'text-cyan-400',    border: 'border-cyan-500/20',    icon: ThumbsUp,     label: 'CONFIRMED' },
  executed:  { bg: 'bg-violet-500/10',   text: 'text-violet-400',  border: 'border-violet-500/20',  icon: Zap,          label: 'EXECUTED' },
  rejected:  { bg: 'bg-red-500/10',      text: 'text-red-400',     border: 'border-red-500/20',     icon: Ban,          label: 'REJECTED' },
};

export default function Approvals() {
  const { data, loading, error, refetch } = useApi('/approvals/all');
  const { messages: wsMessages, connected } = useWebSocket(['approval_decided', 'approval_executed', 'approval_confirmed']);
  const [actionInFlight, setActionInFlight] = useState(null);
  const [selectedTools, setSelectedTools] = useState({});
  const [executionResults, setExecutionResults] = useState({});
  const [executing, setExecuting] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (wsMessages.length > 0) refetch();
  }, [wsMessages, refetch]);

  const handleConfirm = useCallback(async (approvalId) => {
    setActionInFlight(approvalId);
    try {
      await postApi(`/approvals/${approvalId}/confirm`, { decided_by: 'operator' });
      await refetch();
    } catch (e) {
      console.error('Confirm error:', e);
    } finally {
      setActionInFlight(null);
    }
  }, [refetch]);

  const handleExecute = useCallback(async (approvalId, fallbackTools) => {
    setExecuting(approvalId);
    try {
      const manuallySelected = selectedTools[approvalId] || [];
      const tools = manuallySelected.length > 0 ? manuallySelected : (fallbackTools || []);
      const body = { selected_tools: tools };
      const result = await postApi(`/approvals/${approvalId}/execute`, body);
      setExecutionResults(prev => ({ ...prev, [approvalId]: result }));
    } catch (e) {
      setExecutionResults(prev => ({ ...prev, [approvalId]: { error: e.message } }));
    } finally {
      setExecuting(null);
      setTimeout(() => refetch(), 300);
    }
  }, [selectedTools, refetch]);

  const handleReject = useCallback(async (approvalId) => {
    setActionInFlight(approvalId);
    try {
      await postApi(`/approvals/${approvalId}/decide`, { decision: 'rejected', decided_by: 'operator' });
      await refetch();
    } catch (e) {
      console.error('Reject error:', e);
    } finally {
      setActionInFlight(null);
    }
  }, [refetch]);

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
    confirmed: data.filter(a => a.status === 'confirmed').length,
    executed: data.filter(a => a.status === 'executed').length,
    rejected: data.filter(a => a.status === 'rejected').length,
  } : { all: 0, pending: 0, confirmed: 0, executed: 0, rejected: 0 };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Human Review Queue</h1>
          <p className="text-sm text-slate-500 mt-0.5">Every MEDIUM+ event lands here for human review after automated execution</p>
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

      <div className="flex gap-2">
        {['all', 'pending', 'confirmed', 'executed', 'rejected'].map(f => (
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
          Loading review queue...
        </div>
      )}
      {error && <p className="text-red-400">Error: {error}</p>}

      {!loading && filtered.length === 0 && (
        <div className="glass-card p-10 text-center">
          <Shield className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">
            {filter === 'all' ? 'No reviews yet. Run orchestration on a MEDIUM+ window to generate one.'
              : `No ${filter} reviews.`}
          </p>
        </div>
      )}

      {filtered.map((a, i) => {
        const status = a.status || 'pending';
        const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
        const StatusIcon = style.icon;
        const isPending = status === 'pending';
        const isConfirmed = status === 'confirmed';
        const isExecuted = status === 'executed';
        const isRejected = status === 'rejected';
        const isApproved = status === 'approved';
        const execResult = executionResults[a.approval_id];
        const toolsForThis = selectedTools[a.approval_id] || [];

        const hasCorrections = a.review_status === 'corrections_proposed';
        const proposedCorrections = a.proposed_corrections || [];
        const proposedDeferred = a.proposed_deferred || [];
        const allProposed = [...proposedCorrections, ...proposedDeferred];

        return (
          <div key={a.approval_id} className={`glass-card p-5 space-y-3 animate-slide-up ${isRejected ? 'opacity-60' : ''}`}
            style={{ animationDelay: `${i * 80}ms` }}>

            {/* Header */}
            <div className="flex items-center gap-3 flex-wrap">
              <TierBadge tier={a.risk_tier} size="lg" />
              <span className="font-semibold text-white">{a.approval_id}</span>
              <span className="text-xs text-slate-500">
                {a.window_id || a.shipment_id}{a.container_id ? ` / ${a.container_id}` : ''}
              </span>
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
            {a.justification && <p className="text-xs text-slate-500">{a.justification}</p>}

            {/* Deferred notification */}
            {proposedDeferred.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
                <span className="text-[10px] text-blue-400 uppercase tracking-wider font-medium">Awaiting approval:</span>
                {proposedDeferred.map((act, j) => (
                  <span key={j} className="bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded text-[11px] border border-blue-500/15">{act.replace('_agent', '').replace('_', ' ')}</span>
                ))}
              </div>
            )}
            {/* Proposed corrections */}
            {proposedCorrections.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
                <span className="text-[10px] text-amber-400 uppercase tracking-wider font-medium">Corrections:</span>
                {proposedCorrections.map((act, j) => (
                  <span key={j} className="bg-amber-500/10 text-amber-400 px-2 py-0.5 rounded text-[11px] border border-amber-500/15">{act.replace('_agent', '').replace('_', ' ')}</span>
                ))}
              </div>
            )}
            {Array.isArray(a.first_pass_tools) && a.first_pass_tools.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
                <span className="text-[10px] text-emerald-400 uppercase tracking-wider font-medium">First-pass executed:</span>
                {a.first_pass_tools.map((act, j) => (
                  <span key={j} className="bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded text-[11px] border border-emerald-500/15">{act}</span>
                ))}
              </div>
            )}

            {/* ── PENDING REVIEW: The main interactive state ── */}
            {isPending && (
              <div className="pt-3 border-t border-white/[0.06] space-y-4">

                {hasCorrections ? (
                  <div className="bg-amber-500/5 border border-amber-500/10 rounded-xl p-3 space-y-2">
                    <div className="flex items-center gap-2 text-[11px]">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                      <span className="text-amber-400 font-medium">
                        Reflection found quality issues — corrections proposed below. Notification also pending your approval.
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="bg-blue-500/5 border border-blue-500/10 rounded-xl p-3 space-y-2">
                    <div className="flex items-center gap-2 text-[11px]">
                      <Eye className="w-3.5 h-3.5 text-blue-400" />
                      <span className="text-blue-400 font-medium">
                        All tools executed successfully. Approve to send stakeholder notification.
                      </span>
                    </div>
                  </div>
                )}

                {/* Tool selection */}
                <div>
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    {hasCorrections ? 'Corrections pre-selected — deselect to skip, or add more' : 'Optionally select additional tools to run'}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {ALL_TOOLS.map(tool => {
                      const isCorrection = proposedCorrections.includes(tool.id);
                      const isDeferred = proposedDeferred.includes(tool.id);
                      const effectiveSelected = toolsForThis.length > 0
                        ? toolsForThis.includes(tool.id)
                        : (isCorrection || isDeferred);
                      const isFirstPass = Array.isArray(a.first_pass_tools) && a.first_pass_tools.includes(tool.id);
                      return (
                        <button key={tool.id} onClick={() => toggleTool(a.approval_id, tool.id)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                            effectiveSelected && isDeferred
                              ? 'bg-blue-500/15 text-blue-400 border-blue-500/30 shadow-sm shadow-blue-500/10'
                              : effectiveSelected
                                ? 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30 shadow-sm shadow-cyan-500/10'
                                : isFirstPass
                                  ? 'bg-emerald-500/8 text-emerald-400/50 border-emerald-500/10 cursor-not-allowed opacity-50'
                                  : 'bg-white/[0.03] text-slate-500 border-white/[0.06] hover:border-white/[0.12]'
                          }`}
                          disabled={isFirstPass}
                          title={isFirstPass ? 'Already executed in first pass' : isDeferred ? 'Deferred to post-approval' : ''}>
                          {tool.label} {isFirstPass ? '✓' : isDeferred ? '⏳' : ''}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex gap-3 flex-wrap">
                  {toolsForThis.length > 0 ? (
                    <button onClick={() => handleExecute(a.approval_id, allProposed)}
                      disabled={executing === a.approval_id || actionInFlight === a.approval_id}
                      className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-xl text-sm font-semibold hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-500/15">
                      {executing === a.approval_id ? (
                        <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Executing...</>
                      ) : (
                        <><Play className="w-4 h-4" /> Execute {toolsForThis.length} selected tools</>
                      )}
                    </button>
                  ) : (
                    <button onClick={() => handleExecute(a.approval_id, allProposed)}
                      disabled={executing === a.approval_id || actionInFlight === a.approval_id}
                      className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-xl text-sm font-semibold hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-500/15">
                      {executing === a.approval_id ? (
                        <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Executing...</>
                      ) : (
                        <><Play className="w-4 h-4" /> Approve &amp; Execute ({allProposed.length} tools{hasCorrections ? ` incl. ${proposedCorrections.length} corrections` : ''})</>
                      )}
                    </button>
                  )}

                  {hasCorrections && (
                    <button onClick={() => handleExecute(a.approval_id, proposedDeferred)}
                      disabled={executing === a.approval_id || actionInFlight === a.approval_id}
                      className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-emerald-600 to-green-600 text-white rounded-xl text-sm font-semibold hover:from-emerald-500 hover:to-green-500 disabled:opacity-50 transition-all shadow-lg shadow-emerald-500/15">
                      <ThumbsUp className="w-4 h-4" />
                      Skip Corrections — Send Notification Only
                    </button>
                  )}

                  <button onClick={() => handleReject(a.approval_id)}
                    disabled={actionInFlight === a.approval_id}
                    className="flex items-center gap-1.5 px-4 py-2.5 text-red-400 border border-red-500/20 rounded-xl text-sm font-medium hover:bg-red-500/5 disabled:opacity-50 transition-all">
                    <XCircle className="w-4 h-4" /> Reject
                  </button>

                  {actionInFlight === a.approval_id && (
                    <div className="flex items-center gap-2 text-slate-500 text-xs">
                      <div className="w-3.5 h-3.5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
                      Processing...
                    </div>
                  )}
                </div>

                {execResult?.error && (
                  <div className="glass-card-sm p-3 border border-red-500/20 bg-red-500/5">
                    <p className="text-xs text-red-400">Error: {typeof execResult.error === 'object' ? JSON.stringify(execResult.error) : execResult.error}</p>
                  </div>
                )}
              </div>
            )}

            {/* Approved but waiting for user to select tools */}
            {isApproved && (
              <div className="pt-3 border-t border-emerald-500/10 space-y-3">
                <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Select tools to execute</p>
                <div className="flex flex-wrap gap-2">
                  {ALL_TOOLS.map(tool => {
                    const selected = toolsForThis.includes(tool.id);
                    return (
                      <button key={tool.id} onClick={() => toggleTool(a.approval_id, tool.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                          selected ? 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30' : 'bg-white/[0.03] text-slate-500 border-white/[0.06] hover:border-white/[0.12]'
                        }`}>
                        {tool.label}
                      </button>
                    );
                  })}
                </div>
                <button onClick={() => handleExecute(a.approval_id)}
                  disabled={executing === a.approval_id}
                  className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-xl text-sm font-semibold hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-500/15">
                  <Play className="w-4 h-4" />
                  {executing === a.approval_id ? 'Executing...' : `Execute ${toolsForThis.length > 0 ? toolsForThis.length + ' selected' : 'proposed'} tools`}
                </button>
              </div>
            )}

            {/* Confirmed: human said first pass is fine */}
            {isConfirmed && (
              <div className="pt-3 border-t border-cyan-500/10">
                <div className="glass-card-sm p-4 border border-cyan-500/10">
                  <div className="flex items-center gap-2 mb-1">
                    <ThumbsUp className="w-4 h-4 text-cyan-400" />
                    <span className="text-xs font-bold text-cyan-400">Human Confirmed</span>
                    {a.decided_at && <span className="text-[10px] text-slate-600 ml-auto">{new Date(a.decided_at).toLocaleString()}</span>}
                  </div>
                  <p className="text-[11px] text-slate-400">First-pass execution verified as adequate by {a.decided_by || 'operator'}. No additional tools needed.</p>
                </div>
              </div>
            )}

            {/* Executed: corrective tools were run */}
            {isExecuted && (
              <div className="pt-3 border-t border-violet-500/10">
                <div className="glass-card-sm p-4 border border-violet-500/10">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap className="w-4 h-4 text-violet-400" />
                    <span className="text-xs font-bold text-violet-400">Corrective Execution Complete</span>
                    {a.executed_at && <span className="text-[10px] text-slate-600 ml-auto">{new Date(a.executed_at).toLocaleString()}</span>}
                  </div>
                  {Array.isArray(a.executed_tools) && a.executed_tools.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {a.executed_tools.map(t => (
                        <span key={t} className="bg-violet-500/10 text-violet-400 text-[10px] px-2 py-0.5 rounded border border-violet-500/15">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Rejected */}
            {isRejected && (
              <div className="pt-3 border-t border-red-500/10">
                <p className="text-xs text-red-400/70">
                  Rejected by {a.decided_by || 'operator'} — no further execution.
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
