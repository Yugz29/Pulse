import { useState, useEffect, useRef, useCallback } from 'react';
import { marked } from 'marked';

interface Scan {
  filePath: string;
  globalScore: number;
  complexityScore: number;
  functionSizeScore: number;
  churnScore: number;
  depthScore: number;
  paramScore: number;
  fanIn: number;
  fanOut: number;
  language: string;
  trend: '↑' | '↓' | '↔';
  feedback: string | null;
  scannedAt: string;
}

interface Edge {
  from: string;
  to: string;
}

interface FunctionDetail {
  name: string;
  start_line: number;
  line_count: number;
  cyclomatic_complexity: number;
  parameter_count: number;
  max_depth: number;
}

declare global {
  interface Window {
    api: {
      getScans: () => Promise<Scan[]>;
      getEdges: () => Promise<Edge[]>;
      getFunctions: (filePath: string) => Promise<FunctionDetail[]>;
      saveFeedback: (filePath: string, action: string, score: number) => Promise<void>;
      getScoreHistory: (filePath: string) => Promise<{ score: number; scanned_at: string }[]>;
      getFeedbackHistory: (filePath: string) => Promise<{ action: string; created_at: string }[]>;
      askLLM: (ctx: any) => void;
      onLLMChunk: (cb: (chunk: string) => void) => void;
      onLLMDone: (cb: () => void) => void;
      onLLMError: (cb: (err: string) => void) => void;
      onScanComplete: (cb: () => void) => void;
      onEvent: (cb: (e: any) => void) => void;
    };
  }
}

function ScoreGraph({ history, width }: { history: { score: number; scanned_at: string }[], width: number }) {
  if (history.length < 2) return <div style={{ color: '#c7c7cc', fontSize: 11, marginTop: 4 }}>Pas assez de données</div>;

  const W = width - 40, H = 60, pad = 4;
  const scores = history.map(h => h.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores) || 1;
  const pts = scores.map((s, i) => {
    const x = pad + (i / (scores.length - 1)) * (W - pad * 2);
    const y = H - pad - ((s - min) / (max - min || 1)) * (H - pad * 2);
    return `${x},${y}`;
  }).join(' ');

  const lastScore = scores[scores.length - 1] ?? 0;
  const lineColor = lastScore >= 50 ? '#ff3b30' : lastScore >= 20 ? '#ff9500' : '#34c759';

  return (
    <svg width={W} height={H} style={{ display: 'block', marginTop: 4 }}>
      <polyline points={pts} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinejoin="round" />
      {scores.map((s, i) => {
        const x = pad + (i / (scores.length - 1)) * (W - pad * 2);
        const y = H - pad - ((s - min) / (max - min || 1)) * (H - pad * 2);
        return <circle key={i} cx={x} cy={y} r={2.5} fill={lineColor} />;
      })}
    </svg>
  );
}

function Detail({ scan, onClose, onFeedback, sidebarWidth, edges }: {
  scan: Scan;
  onClose: () => void;
  onFeedback: (filePath: string, action: string) => void;
  sidebarWidth: number;
  edges: Edge[];
}) {
  const color = scan.globalScore >= 50 ? '#ff3b30' : scan.globalScore >= 20 ? '#ff9500' : '#34c759';
  const [functions, setFunctions] = useState<FunctionDetail[]>([]);
  const [lastFeedback, setLastFeedback] = useState<string | null>(scan.feedback);
  const [history, setHistory] = useState<{ score: number; scanned_at: string }[]>([]);
  const [llmResponse, setLlmResponse] = useState<string>('');
  const [llmLoading, setLlmLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'metrics' | 'analyse'>('metrics');
  const [feedbackHistory, setFeedbackHistory] = useState<{ action: string; created_at: string }[]>([]);

  useEffect(() => {
    window.api.getFunctions(scan.filePath).then(setFunctions);
    window.api.getScoreHistory(scan.filePath).then(setHistory);
    window.api.getFeedbackHistory(scan.filePath).then(setFeedbackHistory);
  }, [scan.filePath]);

  async function handleFeedback(action: string) {
    await window.api.saveFeedback(scan.filePath, action, scan.globalScore);
    setLastFeedback(action);
    onFeedback(scan.filePath, action);

    if (action === 'explore') {
      setLlmResponse('');
      setLlmLoading(true);
      setActiveTab('analyse');
      window.api.onLLMChunk((chunk) => setLlmResponse(prev => prev + chunk));
      window.api.onLLMDone(() => setLlmLoading(false));
      window.api.onLLMError((err) => { setLlmResponse(`Erreur : ${err}`); setLlmLoading(false); });
      const importedBy = edges
        .filter(e => e.to === scan.filePath)
        .map(e => e.from);
      window.api.askLLM({
        filePath: scan.filePath,
        globalScore: scan.globalScore,
        details: {
          complexityScore: scan.complexityScore,
          functionSizeScore: scan.functionSizeScore,
          churnScore: scan.churnScore,
          depthScore: scan.depthScore,
          paramScore: scan.paramScore,
        },
        functions,
        importedBy,
        scoreHistory: history,
        feedbackHistory,
      });
    }
  }

  const tabStyle = (tab: 'metrics' | 'analyse') => ({
    flex: 1,
    padding: '7px 0',
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    border: 'none',
    borderBottom: activeTab === tab ? '2px solid #1d1d1f' : '2px solid transparent',
    background: 'transparent',
    color: activeTab === tab ? '#1d1d1f' : '#86868b',
    transition: 'all 0.15s',
  } as React.CSSProperties);

  return (
    <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* Header */}
      <div style={{ padding: '16px 16px 0', flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{scan.filePath.split('/').pop()}</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#86868b', fontSize: 18, lineHeight: 1, padding: 0 }}>×</button>
        </div>
        <div style={{ color: '#86868b', fontSize: 10, marginBottom: 10, wordBreak: 'break-all' }}>{scan.filePath}</div>

        {/* Onglets */}
        <div style={{ display: 'flex', borderBottom: '1px solid #e0e0e0', marginBottom: 0 }}>
          <button style={tabStyle('metrics')} onClick={() => setActiveTab('metrics')}>Métriques</button>
          <button style={tabStyle('analyse')} onClick={() => setActiveTab('analyse')}>
            Analyse {llmLoading && '⏳'}
          </button>
        </div>
      </div>

      {/* Contenu scrollable */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>

        {activeTab === 'metrics' && (
          <>
            {/* Graphe historique */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ color: '#86868b', fontSize: 11, marginBottom: 2 }}>Historique</div>
              <ScoreGraph history={history} width={sidebarWidth} />
            </div>

            {/* Métriques */}
            {[
              { label: 'Score global',  value: scan.globalScore.toFixed(1),      color },
              { label: 'Complexité',    value: scan.complexityScore.toFixed(1),   color: '#1d1d1f' },
              { label: 'Taille',        value: scan.functionSizeScore.toFixed(1), color: '#1d1d1f' },
              { label: 'Churn',         value: scan.churnScore.toFixed(1),        color: '#1d1d1f' },
              { label: 'Profondeur',    value: scan.depthScore.toFixed(1),        color: scan.depthScore  > 66 ? '#ff3b30' : scan.depthScore  > 33 ? '#ff9500' : '#1d1d1f' },
              { label: 'Paramètres',   value: scan.paramScore.toFixed(1),         color: scan.paramScore  > 66 ? '#ff3b30' : scan.paramScore  > 33 ? '#ff9500' : '#1d1d1f' },
              { label: 'Fan-in',        value: String(scan.fanIn),                color: scan.fanIn  > 10 ? '#ff3b30' : scan.fanIn  > 5 ? '#ff9500' : '#1d1d1f' },
              { label: 'Fan-out',       value: String(scan.fanOut),               color: scan.fanOut > 10 ? '#ff3b30' : scan.fanOut > 5 ? '#ff9500' : '#1d1d1f' },
              { label: 'Langage',       value: scan.language,                     color: '#1d1d1f' },
              { label: 'Trend',         value: scan.trend,                        color: scan.trend === '↑' ? '#ff3b30' : scan.trend === '↓' ? '#34c759' : '#86868b' },
              { label: 'Feedback',      value: lastFeedback ?? '—',              color: lastFeedback === 'apply' ? '#34c759' : lastFeedback === 'ignore' ? '#86868b' : lastFeedback === 'explore' ? '#ff9500' : '#86868b' },
              { label: 'Scanné le',     value: new Date(scan.scannedAt).toLocaleString(), color: '#86868b' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid #f0f0f0' }}>
                <span style={{ color: '#86868b' }}>{row.label}</span>
                <span style={{ fontWeight: 500, color: row.color }}>{row.value}</span>
              </div>
            ))}

            {/* Boutons feedback */}
            <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
              {['apply', 'ignore', 'explore'].map(action => {
                const isActive = lastFeedback === action;
                const colors: Record<string, string> = { apply: '#34c759', ignore: '#86868b', explore: '#ff9500' };
                return (
                  <button
                    key={action}
                    onClick={() => handleFeedback(action)}
                    style={{
                      flex: 1, padding: '7px 0', borderRadius: 6, fontSize: 11, fontWeight: 600,
                      cursor: 'pointer', border: `1.5px solid ${colors[action]}`,
                      background: isActive ? colors[action] : 'transparent',
                      color: isActive ? '#fff' : colors[action],
                      transition: 'all 0.15s',
                    }}
                  >
                    {action}
                  </button>
                );
              })}
            </div>

            {/* Fonctions */}
            {functions.filter(fn => fn.name !== 'anonymous').length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div style={{ color: '#86868b', fontWeight: 500, marginBottom: 8, fontSize: 11 }}>Fonctions</div>
                {functions.filter(fn => fn.name !== 'anonymous').map(fn => (
                  <div key={fn.name + fn.start_line} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: '#1d1d1f', fontFamily: 'monospace', fontSize: 12 }}>{fn.name}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 11, marginTop: 2 }}>
                      <span style={{ color: '#86868b' }}>l.{fn.start_line}</span>
                      <span style={{ color: '#86868b' }}>{fn.line_count}L</span>
                      <span style={{ color: fn.cyclomatic_complexity > 10 ? '#ff3b30' : fn.cyclomatic_complexity > 5 ? '#ff9500' : '#86868b' }}>cx {fn.cyclomatic_complexity}</span>
                      <span style={{ color: fn.parameter_count > 5 ? '#ff3b30' : '#86868b' }}>{fn.parameter_count}p</span>
                      <span style={{ color: fn.max_depth > 4 ? '#ff3b30' : fn.max_depth > 2 ? '#ff9500' : '#86868b' }}>d{fn.max_depth}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {activeTab === 'analyse' && (
          <>
            {!llmResponse && !llmLoading && (
              <div style={{ color: '#86868b', fontSize: 12, marginTop: 8 }}>
                Clique sur <strong>explore</strong> dans l'onglet Métriques pour lancer l'analyse.
              </div>
            )}
            {llmLoading && (
              <div style={{ color: '#86868b', fontSize: 12, marginBottom: 8 }}>⏳ Analyse en cours…</div>
            )}
            {llmResponse && (
              <>
                <style>{`
                  .pulse-llm h3 { font-size: 13px; font-weight: 600; margin: 14px 0 4px; color: #1d1d1f; }
                  .pulse-llm h2 { font-size: 14px; font-weight: 600; margin: 16px 0 6px; color: #1d1d1f; }
                  .pulse-llm p  { margin: 4px 0 10px; line-height: 1.6; }
                  .pulse-llm ul, .pulse-llm ol { padding-left: 18px; margin: 4px 0 10px; }
                  .pulse-llm li { margin-bottom: 4px; line-height: 1.6; }
                  .pulse-llm pre { background: #f5f5f7; border-radius: 6px; padding: 10px 12px; overflow-x: auto; font-size: 11px; margin: 8px 0; border: 1px solid #e0e0e0; }
                  .pulse-llm code { background: #f0f0f2; border-radius: 3px; padding: 1px 4px; font-size: 11px; font-family: monospace; }
                  .pulse-llm pre code { background: none; padding: 0; }
                  .pulse-llm strong { font-weight: 600; }
                `}</style>
                <div
                  className="pulse-llm"
                  style={{ fontSize: 12, lineHeight: 1.6, color: '#1d1d1f' }}
                  dangerouslySetInnerHTML={{ __html: marked(llmResponse) as string }}
                />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FileList({ scans, selected, onSelect }: { scans: Scan[], selected: Scan | null, onSelect: (s: Scan) => void }) {
  const sorted = [...scans].sort((a, b) => b.globalScore - a.globalScore);

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ borderBottom: '1px solid #e0e0e0' }}>
          <th style={{ textAlign: 'left', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Fichier</th>
          <th style={{ textAlign: 'left', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Lang</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Score</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Complexité</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Churn</th>
          <th style={{ textAlign: 'center', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Trend</th>
          <th style={{ textAlign: 'left', padding: '8px 12px', color: '#86868b', fontWeight: 500 }}>Feedback</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(s => {
          const score = s.globalScore;
          const color = score >= 50 ? '#ff3b30' : score >= 20 ? '#ff9500' : '#34c759';
          const isSelected = selected?.filePath === s.filePath;
          return (
            <tr
              key={s.filePath}
              onClick={() => onSelect(s)}
              style={{ borderBottom: '1px solid #f0f0f0', cursor: 'pointer', background: isSelected ? '#f0f0f5' : 'transparent' }}
            >
              <td style={{ padding: '8px 12px', fontWeight: 500 }}>{s.filePath.split('/').pop()}</td>
              <td style={{ padding: '8px 12px', color: '#86868b' }}>{s.language}</td>
              <td style={{ textAlign: 'right', padding: '8px 12px', color, fontWeight: 600 }}>{score.toFixed(1)}</td>
              <td style={{ textAlign: 'right', padding: '8px 12px', color: '#3a3a3c' }}>{s.complexityScore.toFixed(1)}</td>
              <td style={{ textAlign: 'right', padding: '8px 12px', color: '#3a3a3c' }}>{s.churnScore.toFixed(1)}</td>
              <td style={{ textAlign: 'center', padding: '8px 12px', color: s.trend === '↑' ? '#ff3b30' : s.trend === '↓' ? '#34c759' : '#86868b' }}>{s.trend}</td>
              <td style={{ padding: '8px 12px', color: '#86868b' }}>{s.feedback ?? '—'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function App() {
  const [scans, setScans]       = useState<Scan[]>([]);
  const [edges, setEdges]       = useState<Edge[]>([]);
  const [events, setEvents]     = useState<string[]>([]);
  const [selected, setSelected] = useState<Scan | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(340);
  const isResizing = useRef(false);

  async function load() {
    const [s, e] = await Promise.all([window.api.getScans(), window.api.getEdges()]);
    setScans(s);
    setEdges(e);
  }

  useEffect(() => {
    load();
    window.api.onScanComplete(() => load());
    window.api.onEvent((e: any) => {
      const msg = e.type === 'changed' ? `● ${e.file}` : e.type === 'scan-start' ? '▶ Scanning…' : e.type === 'scan-done' ? `✓ ${e.count} fichiers` : e.type;
      setEvents(prev => [...prev.slice(-19), msg]);
    });
  }, []);

  // Resize handlers
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startW = sidebarWidth;

    const onMove = (ev: MouseEvent) => {
      if (!isResizing.current) return;
      const delta = startX - ev.clientX;
      const newW = Math.min(700, Math.max(260, startW + delta));
      setSidebarWidth(newW);
    };
    const onUp = () => {
      isResizing.current = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [sidebarWidth]);

  const crit = scans.filter(s => s.globalScore >= 50).length;
  const warn = scans.filter(s => s.globalScore >= 20 && s.globalScore < 50).length;

  return (
    <div style={{ background: '#f5f5f7', color: '#1d1d1f', minHeight: '100vh', fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>

      {/* Header */}
      <div style={{ background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(20px)', borderBottom: '1px solid #e0e0e0', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 20, position: 'sticky', top: 0, zIndex: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Pulse</span>
        <span style={{ color: '#86868b', fontSize: 13 }}>{scans.length} fichiers</span>
        <span style={{ color: '#ff3b30', fontSize: 13 }}>{crit} critical</span>
        <span style={{ color: '#ff9500', fontSize: 13 }}>{warn} warning</span>
      </div>

      <div style={{ display: 'flex', height: 'calc(100vh - 45px)' }}>

        {/* Liste principale */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <FileList scans={scans} selected={selected} onSelect={setSelected} />
        </div>

        {/* Sidebar droite */}
        <div style={{ width: sidebarWidth, borderLeft: '1px solid #e0e0e0', background: '#fff', overflowY: 'auto', position: 'relative', flexShrink: 0 }}>

          {/* Poignée de redimensionnement */}
          <div
            onMouseDown={onMouseDown}
            style={{
              position: 'absolute', left: 0, top: 0, bottom: 0, width: 4,
              cursor: 'col-resize', zIndex: 20,
              background: 'transparent',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#e0e0e0')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          />

          {selected ? (
            <Detail
              scan={selected}
              onClose={() => setSelected(null)}
              onFeedback={(filePath, action) => {
                setScans(prev => prev.map(s => s.filePath === filePath ? { ...s, feedback: action } : s));
              }}
              sidebarWidth={sidebarWidth}
              edges={edges}
            />
          ) : (
            <div style={{ padding: 16, fontSize: 12 }}>
              <div style={{ color: '#86868b', marginBottom: 10, fontWeight: 500 }}>Activité</div>
              {events.length === 0 && <div style={{ color: '#c7c7cc' }}>En attente…</div>}
              {events.map((e, i) => (
                <div key={i} style={{ color: '#3a3a3c', marginBottom: 6, lineHeight: 1.4 }}>{e}</div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
