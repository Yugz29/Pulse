import { useState, useEffect, useCallback, useRef } from 'react';
import { useTerminalLLM } from './hooks/useTerminalLLM.js';
import type { Scan, Edge, TerminalErrorNotification } from './types';
import { scoreColor, computeStatus, generateObservations, LLM_STYLES } from './utils';
import ResizeHandle from './components/shared/ResizeHandle';
import SectionLabel from './components/shared/SectionLabel';
import ProjectTrendGraph from './components/shared/ProjectTrendGraph';
import SettingsPanel from './components/SettingsPanel';
import TerminalErrorBanner from './components/TerminalErrorBanner';
import ClipboardHint from './components/ClipboardHint';
import GraphView from './components/GraphView';
import FlowView from './components/FlowView';
import IntelView from './components/IntelView';
import Detail from './components/Detail';
import MemoryView from './components/MemoryView';
export default function App() {
  const [scans,          setScans]          = useState<Scan[]>([]);
  const [edges,          setEdges]          = useState<Edge[]>([]);
  const [events, setEvents] = useState<{ message: string; level: 'info' | 'warn' | 'critical' | 'ok'; type: string }[]>([]);
  const [selected,       setSelected]       = useState<Scan | null>(null);
  const [centerView,     setCenterView]     = useState<'list' | 'graph' | 'flow' | 'intel' | 'memory'>('list');
  const [showSettings,   setShowSettings]   = useState(false);
  const [projectPath,    setProjectPath]    = useState('');
  const [projectHistory, setProjectHistory] = useState<{ date: string; score: number }[]>([]);
  const [socketPort,   setSocketPort]   = useState(7891);
  const [shellCopied, setShellCopied] = useState(false);

  const {
    terminalError, terminalErrorMode, terminalLlm, terminalLlmLoading,
    terminalLlmHtml, setTerminalError, handleAnalyze: handleAnalyzeTerminalError,
    handleDismiss: handleDismissTerminalError, handleResolve: handleResolveTerminalError,
    clearLlm: clearTerminalLlm,
  } = useTerminalLLM();
  const [showZeroScore,      setShowZeroScore]      = useState(false);
  const [activeFilter,       setActiveFilter]       = useState<'critical' | 'stressed' | 'healthy' | 'imported' | 'hotspot' | null>(null);
  const [memories,           setMemories]           = useState<import('./types').MemoryNote[]>([]);

  const intelInputRef = useRef<HTMLInputElement>(null);

  // ── Sidebar resize ────────────────────────────────────────────────────────
  const [leftWidth,      setLeftWidth]      = useState(230);
  const [rightWidth,     setRightWidth]     = useState(300);
  const [leftCollapsed,  setLeftCollapsed]  = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const leftWidthRef  = useRef(leftWidth);
  const rightWidthRef = useRef(rightWidth);
  useEffect(() => { leftWidthRef.current  = leftWidth;  }, [leftWidth]);
  useEffect(() => { rightWidthRef.current = rightWidth; }, [rightWidth]);

  const startResize = useCallback((side: 'left' | 'right', e: React.MouseEvent, currentWidth: number) => {
    e.preventDefault();
    const setFn = side === 'left' ? setLeftWidth : setRightWidth;
    const sign  = side === 'left' ? 1 : -1;
    const [min, max] = side === 'left' ? [160, 420] : [220, 500];
    const startX = e.clientX;
    const onMove = (ev: MouseEvent) => setFn(Math.min(max, Math.max(min, currentWidth + sign * (ev.clientX - startX))));
    const onUp   = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, []);

  // ── Data loading ──────────────────────────────────────────────────────────
  async function load() {
    const [s, e, h] = await Promise.all([
      window.api.getScans(),
      window.api.getEdges(),
      window.api.getProjectScoreHistory(),
    ]);
    setScans(s); setEdges(e); setProjectHistory(h);
  }

  useEffect(() => {
    window.api.getProjectPath().then(setProjectPath);
    load();
    window.api.onScanComplete(() => load());
    window.api.onEvent((e: any) => {
      // Événements fichier direct du watcher (changed/added/deleted)
      if (e.type === 'changed' || e.type === 'added' || e.type === 'deleted') {
        const file = e.file ?? '';
        const msg  = e.type === 'changed' ? `${file} · modified`
                   : e.type === 'added'   ? `${file} · added`
                   : `${file} · deleted`;
        setEvents(prev => [...prev.slice(-49), { message: msg, level: 'info', type: e.type }]);
        return;
      }
      // Événements enrichis du scan
      if (e.message) {
        setEvents(prev => [...prev.slice(-49), { message: e.message, level: e.level ?? 'info', type: e.type }]);
      }
    });
    window.api.onTerminalError(ctx => setTerminalError(ctx));
    window.api.getSocketPort().then(setSocketPort);
    window.api.getMemories().then(setMemories);
    const offMemories  = window.api.onMemoriesUpdated(() => window.api.getMemories().then(setMemories));
    const offFocusFile = window.api.onFocusFile(filePath => {
      setCenterView('list');
      window.api.getScans().then(latest => {
        const scan = latest.find(s => s.filePath === filePath);
        if (scan) setSelected(scan);
      });
    });

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCenterView('intel');
        setTimeout(() => intelInputRef.current?.focus(), 50);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      offMemories();
      offFocusFile();
    };
  }, []);



  function copyShellSnippet() {
    const snippet = `# Pulse shell integration\n_pulse_preexec() { __pulse_cmd="$1"; }\n_pulse_precmd() {\n  local code=$?\n  [ "$code" -ne 0 ] && [ -n "$__pulse_cmd" ] && \\\n    curl -s --max-time 0.3 -X POST http://localhost:${socketPort}/command-error \\\n      -H 'Content-Type: application/json' \\\n      -d "{\\"command\\":\\"$__pulse_cmd\\",\\"exit_code\\":$code,\\"cwd\\":\\"$PWD\\",\\"timestamp\\":$(date +%s)}" \\\n      2>/dev/null &\n  __pulse_cmd=""\n}\nautoload -Uz add-zsh-hook\nadd-zsh-hook preexec _pulse_preexec\nadd-zsh-hook precmd _pulse_precmd`;
    navigator.clipboard.writeText(snippet).then(() => {
      setShellCopied(true);
      setTimeout(() => setShellCopied(false), 2000);
    });
  }

  // ── Derived state ─────────────────────────────────────────────────────────
  const status    = computeStatus(scans);
  const sorted    = [...scans].sort((a, b) => b.globalScore - a.globalScore);
  const showRight = selected !== null || terminalLlm !== '' || terminalLlmLoading;

  const stable   = scans.filter(s => s.globalScore < 20).length;
  const stressed = scans.filter(s => s.globalScore >= 20 && s.globalScore < 50).length;
  const critical = scans.filter(s => s.globalScore >= 50).length;
  const projName = projectPath ? projectPath.split('/').pop() || projectPath : '—';

  const currentScore = projectHistory.length > 0 ? projectHistory[projectHistory.length - 1]!.score : status.tension;
  const prevScore    = projectHistory.length >= 2 ? projectHistory[projectHistory.length - 2]!.score : null;
  const delta        = prevScore !== null ? currentScore - prevScore : null;
  const deltaStr     = delta === null ? '' : (delta > 0 ? '+' : '') + delta.toFixed(1);

  // ── Context adaptatif ────────────────────────────────────────────────────
  // Aligné avec computeStatus : mêmes seuils
  const critRatio   = scans.length > 0 ? critical / scans.length : 0;
  const isCritical  = critRatio > 0.2  || currentScore >= 50;
  const isStressed  = !isCritical && (critRatio >= 0.1 || currentScore >= 20);
  const isMostly    = !isCritical && !isStressed && critical > 0;
  const isHealthy   = !isCritical && !isStressed && !isMostly;

  const healthLabel = isCritical ? 'Critical' : isStressed ? 'Stressed' : isMostly ? 'Mostly Stable' : 'Healthy';
  const healthColor = isCritical ? '#ef4444'  : isStressed ? '#f97316'  : isMostly ? '#eab308'       : '#22c55e';
  const health      = Math.max(0, 100 - currentScore);

  const activeFiles = scans.filter(s => s.rawChurn > 0).length;
  const highChurn   = scans.filter(s => s.rawChurn >= 10).length;
  const hubCount    = scans.filter(s => s.fanIn >= 5).length;
  const worsening   = scans.filter(s => s.trend === '↑').length;

  // Deux lignes de contexte narratif, ton adaptatif
  const line1 = scans.length === 0 ? 'no modules scanned yet' : [
    stable   > 0 ? `${stable} healthy` : null,
    stressed > 0 ? `${stressed} stressed` : null,
    critical > 0 ? `${critical} critical` : null,
    `${scans.length} modules`,
  ].filter(Boolean).join(' · ');

  const line2parts: string[] = [];
  if (activeFiles > 0)  line2parts.push(`${activeFiles} file${activeFiles > 1 ? 's' : ''} active last 30d${highChurn > 0 ? ` · ${highChurn} high-frequency` : ''}`);
  if (hubCount > 0) {
    const hubRisk = scans.filter(s => s.fanIn >= 5 && s.globalScore >= 30).length;
    line2parts.push(hubRisk > 0
      ? `${hubRisk} high-risk hub${hubRisk > 1 ? 's' : ''}`
      : `${hubCount} widely imported file${hubCount > 1 ? 's' : ''}`);
  }
  if (worsening > 0 && !isHealthy) line2parts.push(`${worsening} degrading`);
  if (delta !== null && Math.abs(delta) > 0.1) line2parts.push(`trend ${deltaStr} pts`);
  if (line2parts.length === 0) line2parts.push(isHealthy ? 'no coupling risk · stable' : 'no notable activity');
  const line2 = line2parts.join(' · ');

  const viewTabStyle = (v: 'list' | 'graph' | 'flow' | 'intel'): React.CSSProperties => ({
    fontSize: 9, letterSpacing: '0.14em', fontWeight: 700, padding: '4px 10px',
    cursor: 'pointer', border: 'none', background: 'transparent',
    color: centerView === v ? '#d0d0d8' : '#3a3a44', fontFamily: 'monospace',
    borderBottom: centerView === v ? '1px solid #4a9eff' : '1px solid transparent',
    transition: 'color 0.15s',
  });

  return (
    <div style={{ background: '#0a0a0b', color: '#d0d0d8', height: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'monospace', overflow: 'hidden', position: 'relative' }}>

      {/* ── TOP BAR ─────────────────────────────────────────────────────────── */}
      <div style={{ height: 42, borderBottom: '1px solid #1e1e22', display: 'flex', alignItems: 'center', padding: '0 20px', gap: 16, flexShrink: 0 }}>
        <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.2em', color: '#e8e8ea' }}>PULSE</span>
        <span style={{ color: '#1e1e22', fontSize: 14 }}>|</span>
        <span style={{ fontSize: 11, color: '#6a6a72' }}>{scans.length} modules</span>
        <div style={{ flex: 1 }} />
        {memories.length > 0 && (() => {
          const latest = [...memories].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())[0]!;
          const subject = latest.subject.split('/').pop() ?? latest.subject;
          return (
            <div
              onClick={() => setCenterView('memory')}
              style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', opacity: centerView === 'memory' ? 1 : 0.7, transition: 'opacity 0.15s' }}
              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
              onMouseLeave={e => e.currentTarget.style.opacity = centerView === 'memory' ? '1' : '0.7'}
            >
              <span style={{ fontSize: 7, color: '#22c55e', lineHeight: 1 }}>●</span>
              <span style={{ fontSize: 9, color: '#3a3a44', letterSpacing: '0.06em', borderBottom: centerView === 'memory' ? '1px solid #3a3a44' : '1px solid transparent' }}>memory</span>
              <span style={{ fontSize: 9, color: '#2a2a32' }}>· {memories.length}</span>
              <span style={{ fontSize: 9, color: '#2a2a32', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>· {subject}</span>
            </div>
          );
        })()}
        <span style={{ color: '#1e1e22', fontSize: 14 }}>|</span>
        <span style={{ fontSize: 11, color: status.color, letterSpacing: '0.1em', fontWeight: 600 }}>{status.label.toUpperCase()}</span>
        <button onClick={() => setShowSettings(true)} title="Settings"
          style={{ background: 'none', border: '1px solid transparent', borderRadius: 3, color: '#4a4a52', cursor: 'pointer', fontSize: 14, padding: '2px 6px', lineHeight: 1, fontFamily: 'monospace', transition: 'color 0.15s, border-color 0.15s' }}
          onMouseEnter={e => { e.currentTarget.style.color = '#8a8a94'; e.currentTarget.style.borderColor = '#2e2e34'; }}
          onMouseLeave={e => { e.currentTarget.style.color = '#4a4a52'; e.currentTarget.style.borderColor = 'transparent'; }}
        >⚙️</button>
      </div>

      {/* ── SETTINGS OVERLAY ────────────────────────────────────────────────── */}
      {showSettings && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 200 }}>
          <SettingsPanel onClose={() => setShowSettings(false)} />
        </div>
      )}

      {/* ── TERMINAL ERROR BANNER (mode error) ──────────────────────────────── */}
      {terminalError && terminalError.mode === 'error' && (
        <TerminalErrorBanner
          ctx={terminalError}
          onDismiss={handleDismissTerminalError}
          onAnalyze={handleAnalyzeTerminalError}
          onResolve={handleResolveTerminalError}
        />
      )}

      {/* ── CLIPBOARD HINT (mode hint) ───────────────────────────────────── */}
      {terminalError && terminalError.mode === 'hint' && (
        <ClipboardHint
          text={terminalError.errorText}
          loading={terminalLlmLoading}
          onDismiss={handleDismissTerminalError}
          onExplain={handleAnalyzeTerminalError}
        />
      )}

      {/* ── MAIN LAYOUT ─────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* LEFT – Watchboard */}
        <div style={{ width: leftCollapsed ? 0 : leftWidth, minWidth: leftCollapsed ? 0 : leftWidth, display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden', transition: leftCollapsed ? 'width 0.2s, min-width 0.2s' : 'none' }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px 0' }}>

            <div style={{ padding: '0 16px 4px' }}>
              <div style={{ marginBottom: 10 }}><SectionLabel>{projName.toUpperCase()}</SectionLabel></div>
              {generateObservations(scans, edges).map((obs, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '5px 0', borderBottom: '1px solid #0e0e10' }}>
                  <span style={{ color: '#2e2e34', fontSize: 9, marginTop: 2, flexShrink: 0 }}>›</span>
                  <span style={{ fontSize: 10, color: i === 0 ? '#6a6a72' : '#4a4a52', lineHeight: 1.5 }}>{obs}</span>
                </div>
              ))}
            </div>

            {events.length > 0 && (
              <div style={{ borderTop: '1px solid #111113', padding: '14px 16px 4px' }}>
                <div style={{ marginBottom: 10 }}><SectionLabel>ACTIVITY</SectionLabel></div>
                {[...events].reverse().slice(0, 16).map((ev, i) => {
                  const dotColor = ev.level === 'critical' ? '#ef4444'
                                 : ev.level === 'warn'     ? '#f97316'
                                 : ev.level === 'ok'       ? '#22c55e'
                                 : i === 0                 ? '#4a9eff'
                                 : '#1e1e22';
                  const textColor = i === 0
                    ? ev.level === 'critical' ? '#ef4444'
                    : ev.level === 'warn'     ? '#f97316'
                    : ev.level === 'ok'       ? '#22c55e'
                    : '#8a8a94'
                    : ev.level === 'critical' ? '#6a2222'
                    : ev.level === 'warn'     ? '#6a3a22'
                    : ev.level === 'ok'       ? '#1a4a2a'
                    : '#3a3a44';
                  return (
                    <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #0e0e10', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                      <span style={{ width: 4, height: 4, borderRadius: '50%', flexShrink: 0, marginTop: 4, background: dotColor }} />
                      <span style={{ fontSize: 10, color: textColor, lineHeight: 1.5 }}>{ev.message}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* HANDLE LEFT */}
        <ResizeHandle
          onMouseDown={e => { if (leftCollapsed) { setLeftCollapsed(false); return; } startResize('left', e, leftWidthRef.current); }}
          onToggle={() => setLeftCollapsed(c => !c)}
          collapsed={leftCollapsed}
          collapseToward="left"
        />

        {/* CENTER */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

          {/* Project header */}
          <div style={{ padding: '22px 40px 0', flexShrink: 0, borderBottom: '1px solid #1e1e22' }}>

            {/* Row 1 : nom + % + graph */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20, marginBottom: 14 }}>

              {/* Gauche */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Nom + badge + CHANGE */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 16, fontWeight: 600, color: '#e8e8ea' }}>{projName}</span>
                  <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.12em', padding: '2px 6px', borderRadius: 2, color: healthColor, border: `1px solid ${healthColor}22`, background: `${healthColor}0d` }}>
                    {healthLabel.toUpperCase()}
                  </span>
                  <button onClick={() => window.api.pickProject().then(p => { if (p) setProjectPath(p); })}
                    style={{ marginLeft: 'auto', padding: '2px 8px', borderRadius: 2, fontSize: 9, fontWeight: 700, cursor: 'pointer', border: '1px solid #1e1e22', background: 'transparent', color: '#3a3a44', fontFamily: 'monospace', letterSpacing: '0.1em', transition: 'border-color 0.15s, color 0.15s' }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = '#4a9eff'; e.currentTarget.style.color = '#4a9eff'; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = '#1e1e22'; e.currentTarget.style.color = '#3a3a44'; }}
                  >CHANGE</button>
                </div>
                <div style={{ fontSize: 9, color: '#2e2e36', marginBottom: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{projectPath}</div>

                {/* Barre de distribution */}
                {scans.length > 0 && (
                  <div style={{ display: 'flex', height: 5, borderRadius: 2, overflow: 'hidden', gap: 1, marginBottom: 10 }}>
                    {stable   > 0 && <div style={{ flex: stable,   background: '#22c55e', opacity: 0.75 }} />}
                    {stressed > 0 && <div style={{ flex: stressed, background: '#f97316', opacity: 0.75 }} />}
                    {critical > 0 && <div style={{ flex: critical, background: '#ef4444', opacity: 0.85 }} />}
                  </div>
                )}

                {/* Lignes narratives */}
                {(() => {
                  const linkStyle = (filter: typeof activeFilter, color: string): React.CSSProperties => ({
                    color,
                    cursor: 'pointer',
                    borderBottom: activeFilter === filter ? `1px solid ${color}` : '1px solid transparent',
                    transition: 'border-color 0.15s, opacity 0.15s',
                  });
                  const toggle = (filter: typeof activeFilter) => {
                    setActiveFilter(f => f === filter ? null : filter);
                    setCenterView('list');
                  };
                  return (
                    <>
                      <div style={{ fontSize: 10, lineHeight: 1.8 }}>
                        {stable   > 0 && <><span style={linkStyle('healthy',  '#22c55e')} onClick={() => toggle('healthy')}  onMouseEnter={e => e.currentTarget.style.opacity='0.7'} onMouseLeave={e => e.currentTarget.style.opacity='1'}>{stable} healthy</span><span style={{ color: '#2a2a32' }}> · </span></>}
                        {stressed > 0 && <><span style={linkStyle('stressed', '#f97316')} onClick={() => toggle('stressed')} onMouseEnter={e => e.currentTarget.style.opacity='0.7'} onMouseLeave={e => e.currentTarget.style.opacity='1'}>{stressed} stressed</span><span style={{ color: '#2a2a32' }}> · </span></>}
                        {critical > 0 && <><span style={linkStyle('critical', '#ef4444')} onClick={() => toggle('critical')} onMouseEnter={e => e.currentTarget.style.opacity='0.7'} onMouseLeave={e => e.currentTarget.style.opacity='1'}>{critical} critical</span><span style={{ color: '#2a2a32' }}> · </span></>}
                        <span style={{ color: '#3a3a44' }}>{scans.length} modules</span>
                      </div>
                      <div style={{ fontSize: 10, lineHeight: 1.8, color: '#3a3a44' }}>
                        {line2parts.map((part, i) => {
                          const isImported  = part.includes('imported') || part.includes('hub');
                          const isChurn     = part.includes('active');
                          const isDegrading = part.includes('degrading');
                          const isTrend     = part.includes('trend');
                          const color = isDegrading ? '#ef4444'
                                      : isImported  ? '#f97316'
                                      : isChurn     ? '#6a8aaa'
                                      : isTrend && delta !== null && delta > 0 ? '#ef4444'
                                      : isTrend && delta !== null && delta < 0 ? '#22c55e'
                                      : '#3a3a44';
                          const filter: typeof activeFilter = isImported ? 'imported' : isChurn ? 'hotspot' : null;
                          return (
                            <span key={i}>
                              {i > 0 && <span style={{ color: '#2a2a32' }}> · </span>}
                              <span
                                style={{ color, cursor: filter ? 'pointer' : 'default', borderBottom: activeFilter === filter && filter ? `1px solid ${color}` : '1px solid transparent', transition: 'opacity 0.15s' }}
                                onClick={() => filter && toggle(filter)}
                                onMouseEnter={e => { if (filter) e.currentTarget.style.opacity = '0.7'; }}
                                onMouseLeave={e => { if (filter) e.currentTarget.style.opacity = '1'; }}
                              >{part}</span>
                            </span>
                          );
                        })}
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* Droite : % health + sous-label + graph */}
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, flexShrink: 0 }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 2, justifyContent: 'flex-end' }}>
                    <span style={{ fontSize: 34, fontWeight: 200, color: healthColor, lineHeight: 1 }}>{health.toFixed(0)}</span>
                    <span style={{ fontSize: 12, color: '#3a3a44', marginBottom: 1 }}>%</span>
                  </div>
                  <div style={{ fontSize: 9, color: '#3a3a44', marginTop: 2, textAlign: 'right' }}>
                    risk {currentScore.toFixed(1)} · {isHealthy ? 'low' : isStressed ? 'moderate' : 'high'}
                    {delta !== null && Math.abs(delta) > 0.1 && <span style={{ color: delta > 0 ? '#ef4444' : '#22c55e' }}> · {deltaStr}</span>}
                  </div>
                </div>
                {projectHistory.length >= 2 && (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                    <ProjectTrendGraph history={projectHistory} />
                    <span style={{ fontSize: 9, color: '#2a2a32' }}>{projectHistory.length}d</span>
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', borderTop: '1px solid #111113', marginLeft: -40, marginRight: -40, paddingLeft: 40 }}>
              <button style={viewTabStyle('list')}    onClick={() => setCenterView('list')}>LIST</button>
              <button style={viewTabStyle('graph')}   onClick={() => setCenterView('graph')}>GRAPH</button>
              <button style={viewTabStyle('flow')}    onClick={() => setCenterView('flow')}>FLOW</button>
              <button style={viewTabStyle('intel')}   onClick={() => { setCenterView('intel'); setTimeout(() => intelInputRef.current?.focus(), 50); }}>INTEL</button>
            </div>
          </div>

          {/* Views */}
          {centerView === 'list' && (() => {
            // Détection des noms de fichiers en doublon
            const nameCounts = new Map<string, number>();
            sorted.forEach(s => {
              const name = s.filePath.split('/').pop() ?? '';
              nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1);
            });
            const zeroCount  = sorted.filter(s => s.globalScore === 0).length;
            const filtered   = activeFilter === 'critical' ? sorted.filter(s => s.globalScore >= 50)
                             : activeFilter === 'stressed' ? sorted.filter(s => s.globalScore >= 20 && s.globalScore < 50)
                             : activeFilter === 'healthy'  ? sorted.filter(s => s.globalScore < 20)
                             : activeFilter === 'imported' ? sorted.filter(s => s.fanIn >= 5)
                             : activeFilter === 'hotspot'  ? [...scans].filter(s => s.hotspotScore > 0).sort((a, b) => b.hotspotScore - a.hotspotScore)
                             : sorted;
            const visible    = filtered.filter(s => showZeroScore || s.globalScore > 0);
            return (
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {/* Header liste + toggle */}
                <div style={{ padding: '14px 40px 8px', display: 'flex', alignItems: 'center', gap: 12 }}>
                  <SectionLabel>MODULES</SectionLabel>
                  {activeFilter && (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ fontSize: 9, color:
                        activeFilter === 'critical' ? '#ef4444' :
                        activeFilter === 'stressed' ? '#f97316' :
                        activeFilter === 'healthy'  ? '#22c55e' :
                        activeFilter === 'hotspot'  ? '#6a8aaa' : '#f97316',
                        letterSpacing: '0.08em', fontFamily: 'monospace' }}>
                        {activeFilter}
                      </span>
                      <button onClick={() => setActiveFilter(null)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: '#3a3a44', padding: 0, lineHeight: 1, fontFamily: 'monospace', transition: 'color 0.15s' }}
                        onMouseEnter={e => e.currentTarget.style.color = '#8a8a94'}
                        onMouseLeave={e => e.currentTarget.style.color = '#3a3a44'}
                        title="clear filter"
                      >×</button>
                    </span>
                  )}
                  {zeroCount > 0 && !activeFilter && (
                    <button onClick={() => setShowZeroScore(v => !v)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 9, color: showZeroScore ? '#4a9eff' : '#3a3a44', fontFamily: 'monospace', letterSpacing: '0.08em', padding: 0, transition: 'color 0.15s' }}
                      title={showZeroScore ? 'hide zero-score files' : `show ${zeroCount} zero-score files`}
                    >
                      {showZeroScore ? `▼ hide ${zeroCount} empty` : `▶ +${zeroCount} empty`}
                    </button>
                  )}
                </div>
                {visible.map(s => {
                  const c          = scoreColor(s.globalScore);
                  const isSelected = selected?.filePath === s.filePath;
                  const name       = s.filePath.split('/').pop() ?? s.filePath;
                  const isDuplicate = (nameCounts.get(name) ?? 0) > 1;
                  // Dossier parent pour les doublons
                  const parts      = s.filePath.split('/');
                  const parent     = parts.length >= 2 ? parts[parts.length - 2] : '';
                  return (
                    <div key={s.filePath} onClick={() => setSelected(isSelected ? null : s)}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 40px', borderBottom: '1px solid #0d0d0f', cursor: 'pointer', background: isSelected ? '#111113' : 'transparent', transition: 'background 0.1s' }}
                      onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = '#0d0d0f'; }}
                      onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
                    >
                      <div style={{ width: 2, height: 16, background: c, borderRadius: 1, flexShrink: 0, opacity: s.globalScore === 0 ? 0.15 : isSelected ? 1 : 0.5 }} />
                      <span style={{ flex: 1, fontSize: 12, color: s.globalScore === 0 ? '#2a2a32' : isSelected ? '#e8e8ea' : '#a0a0a8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {name}
                        {isDuplicate && <span style={{ fontSize: 9, color: '#3a3a44', marginLeft: 6 }}>{parent}/</span>}
                      </span>
                      {s.globalScore > 0 && (
                        <span style={{ fontSize: 11, color: isSelected ? c : '#6a6a72', flexShrink: 0, minWidth: 32, textAlign: 'right', fontWeight: isSelected ? 600 : 400 }}>
                          {s.globalScore.toFixed(1)}
                        </span>
                      )}
                      {s.globalScore > 0 && (
                        <span style={{ fontSize: 11, flexShrink: 0, width: 14, textAlign: 'center', color: s.trend === '↑' ? '#ef4444' : s.trend === '↓' ? '#22c55e' : '#3a3a44' }}>
                          {s.trend}
                        </span>
                      )}
                      {s.hotspotScore >= 15 && (
                        <span style={{ fontSize: 9, color: s.hotspotScore >= 60 ? '#ef4444' : '#f97316', flexShrink: 0, fontFamily: 'monospace', letterSpacing: '0.06em', minWidth: 28, textAlign: 'right', opacity: 0.75 }}>
                          ◆ {s.hotspotScore.toFixed(0)}
                        </span>
                      )}
                    </div>
                  );
                })}
                {sorted.length === 0 && <div style={{ padding: '24px 40px', fontSize: 11, color: '#4a4a52' }}>Awaiting first scan…</div>}
              </div>
            );
          })()}

          {centerView === 'graph'   && <GraphView    scans={scans} edges={edges} onSelect={setSelected} selectedPath={selected?.filePath ?? null} />}
          {centerView === 'flow'    && <FlowView     scans={scans} edges={edges} onSelect={setSelected} selectedPath={selected?.filePath ?? null} />}
          {centerView === 'intel'   && <IntelView    scans={scans} edges={edges} projectHistory={projectHistory} projectPath={projectPath} selectedFile={selected} inputRef={intelInputRef} />}
          {centerView === 'memory' && (
            <MemoryView
              notes={memories}
              onDismiss={id => {
                window.api.dismissMemory(id);
                setMemories(prev => prev.filter(n => n.id !== id));
              }}
              onSelect={subject => {
                const scan = scans.find(s => s.filePath === subject);
                if (scan) { setSelected(scan); setCenterView('list'); }
              }}
            />
          )}
        </div>

        {/* HANDLE RIGHT */}
        {showRight && (
          <ResizeHandle
            onMouseDown={e => { if (rightCollapsed) { setRightCollapsed(false); return; } startResize('right', e, rightWidthRef.current); }}
            onToggle={() => setRightCollapsed(c => !c)}
            collapsed={rightCollapsed}
            collapseToward="right"
          />
        )}

        {/* RIGHT – Detail / Terminal Analysis */}
        {showRight && (
          <div style={{ width: rightCollapsed ? 0 : rightWidth, minWidth: rightCollapsed ? 0 : rightWidth, background: '#0d0d0f', transition: rightCollapsed ? 'width 0.2s, min-width 0.2s' : 'none', display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden' }}>
            {(terminalLlm || terminalLlmLoading) ? (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'monospace' }}>
                <style>{LLM_STYLES}</style>
                <div style={{ padding: '14px 16px', borderBottom: '1px solid #1e1e22', flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 10, letterSpacing: '0.14em', color: terminalErrorMode === 'hint' ? '#4a9eff' : '#ef4444', fontWeight: 700 }}>
                    {terminalErrorMode === 'hint' ? 'CLIPBOARD EXPLAIN' : 'ERROR ANALYSIS'}
                  </span>
                  <button onClick={clearTerminalLlm} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4a4a52', fontSize: 16, padding: 0, lineHeight: 1 }}>×</button>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
                  {terminalLlmLoading && !terminalLlm && <div style={{ color: '#4a4a52', fontSize: 11 }}>Analyzing…</div>}
                  {terminalLlmHtml && (
                    <div className="pulse-llm" style={{ fontSize: 11, lineHeight: 1.65 }}
                      dangerouslySetInnerHTML={{ __html: terminalLlmHtml }}
                    />
                  )}
                </div>
              </div>
            ) : selected ? (
              <Detail
                scan={selected}
                onClose={() => setSelected(null)}
                onFeedback={(filePath, action) => setScans(prev => prev.map(s => s.filePath === filePath ? { ...s, feedback: action } : s))}
                edges={edges}
              />
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
