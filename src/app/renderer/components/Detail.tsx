import { useState, useEffect, useRef } from 'react';
import { marked } from 'marked';
import type { Scan, Edge, FunctionDetail } from '../types';
import { scoreColor, classifyLayer, LAYER_LABELS, LAYER_COLORS, LLM_STYLES } from '../utils';
import ScoreGraph from './shared/ScoreGraph';
import MetricBar from './shared/MetricBar';
import SectionLabel from './shared/SectionLabel';

interface Props {
  scan: Scan;
  onClose: () => void;
  onFeedback: (filePath: string, action: string) => void;
  edges: Edge[];
}

export default function Detail({ scan, onClose, onFeedback, edges }: Props) {
  const [functions,       setFunctions]       = useState<FunctionDetail[]>([]);
  const [history,         setHistory]         = useState<{ score: number; scanned_at: string }[]>([]);
  const [memories,        setMemories]        = useState<import('../types').MemoryNote[]>([]);
  const [llmResponse,     setLlmResponse]     = useState('');
  const [llmLoading,      setLlmLoading]      = useState(false);
  const [llmThinking,     setLlmThinking]     = useState(false);
  const [activeTab,       setActiveTab]       = useState<'metrics' | 'analyse' | 'memory'>('metrics');
  const [feedbackHistory, setFeedbackHistory] = useState<{ action: string; created_at: string }[]>([]);
  const [llmFromCache,    setLlmFromCache]    = useState(false);
  const llmCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => { llmCleanupRef.current?.(); };
  }, []);

  useEffect(() => {
    llmCleanupRef.current?.();
    llmCleanupRef.current = null;
    setLlmResponse('');
    setLlmFromCache(false);
    setLlmLoading(false);
    setLlmThinking(false);
    window.api.getFunctions(scan.filePath).then(setFunctions);
    window.api.getScoreHistory(scan.filePath).then(setHistory);
    window.api.getMemoriesForFile(scan.filePath).then(setMemories);
    window.api.getFeedbackHistory(scan.filePath).then(setFeedbackHistory);
    window.api.getLlmReport(scan.filePath).then(report => {
      if (report) { setLlmResponse(report); setLlmFromCache(true); }
    });

    // Re-charge les mémoires quand le moteur en extrait de nouvelles
    const offMemories = window.api.onMemoriesUpdated(
      () => window.api.getMemoriesForFile(scan.filePath).then(setMemories)
    );
    return () => offMemories();
  }, [scan.filePath]);

  function handleExplore() {
    llmCleanupRef.current?.();
    llmCleanupRef.current = null;
    setLlmResponse('');
    setLlmFromCache(false);
    setLlmLoading(true);
    setLlmThinking(true);

    const importedBy = edges.filter(e => e.to === scan.filePath).map(e => e.from);
    const cleanup = () => { offChunk(); offDone(); offError(); };

    const offChunk = window.api.onLLMChunk(chunk => {
      setLlmThinking(false);
      setLlmResponse(prev => prev + chunk);
    });
    const offDone  = window.api.onLLMDone(() => {
      setLlmLoading(false);
      setLlmThinking(false);
      llmCleanupRef.current = null;
      cleanup();
    });
    const offError = window.api.onLLMError(err => {
      setLlmResponse(`Error: ${err}`);
      setLlmLoading(false);
      setLlmThinking(false);
      llmCleanupRef.current = null;
      cleanup();
    });

    llmCleanupRef.current = cleanup;
    window.api.askLLM({
      filePath: scan.filePath, globalScore: scan.globalScore,
      details: { complexityScore: scan.complexityScore, functionSizeScore: scan.functionSizeScore, churnScore: scan.churnScore, depthScore: scan.depthScore, paramScore: scan.paramScore },
      rawValues: { complexity: scan.rawComplexity, cognitiveComplexity: scan.rawCognitiveComplexity ?? 0, functionSize: scan.rawFunctionSize, depth: scan.rawDepth, params: scan.rawParams, churn: scan.rawChurn },
      functions, importedBy, scoreHistory: history, feedbackHistory,
    });
  }

  const color = scoreColor(scan.globalScore);
  const tabStyle = (tab: 'metrics' | 'analyse' | 'memory'): React.CSSProperties => ({
    flex: 1, padding: '7px 0', fontSize: 10, letterSpacing: '0.12em', fontWeight: 600,
    cursor: 'pointer', border: 'none',
    borderBottom: activeTab === tab ? '1px solid #4a9eff' : '1px solid transparent',
    background: 'transparent',
    color: activeTab === tab ? '#d0d0d8' : '#4a4a52',
    transition: 'color 0.15s', fontFamily: 'monospace',
  });

  const l = classifyLayer(scan.filePath);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'monospace' }}>
      <style>{LLM_STYLES}</style>

      {/* Header */}
      <div style={{ padding: '14px 16px 0', flexShrink: 0, borderBottom: '1px solid #1e1e22' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, color: '#e8e8ea', fontWeight: 600, marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {scan.filePath.split('/').pop()}
            </div>
            <div style={{ fontSize: 9, color: '#4a4a52', wordBreak: 'break-all', lineHeight: 1.4 }}>{scan.filePath}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4a4a52', fontSize: 16, padding: '0 0 0 8px', flexShrink: 0, lineHeight: 1 }}>×</button>
        </div>

        <div style={{ marginBottom: 6 }}>
          <span style={{ fontSize: 9, letterSpacing: '0.12em', fontWeight: 700, color: LAYER_COLORS[l], border: `1px solid ${LAYER_COLORS[l]}`, borderRadius: 2, padding: '1px 6px', opacity: 0.8 }}>
            {LAYER_LABELS[l]}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, padding: '8px 0 10px' }}>
          <span style={{ fontSize: 34, fontWeight: 300, color, lineHeight: 1 }}>{scan.globalScore.toFixed(1)}</span>
          <span style={{ fontSize: 10, color: '#4a4a52' }}>tension score</span>
          <span style={{ marginLeft: 'auto', fontSize: 20, color: scan.trend === '↑' ? '#ef4444' : scan.trend === '↓' ? '#22c55e' : '#4a4a52', lineHeight: 1 }}>
            {scan.trend}
          </span>
        </div>

        <div style={{ display: 'flex' }}>
          <button style={tabStyle('metrics')} onClick={() => setActiveTab('metrics')}>METRICS</button>
          <button style={tabStyle('analyse')} onClick={() => setActiveTab('analyse')}>
            ANALYSIS{llmLoading ? ' …' : ''}
          </button>
          <button style={tabStyle('memory')} onClick={() => setActiveTab('memory')}>
            MEMORY{memories.length > 0 ? ` · ${memories.length}` : ''}
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
        {activeTab === 'metrics' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 6 }}><SectionLabel>HISTORY</SectionLabel></div>
              <ScoreGraph history={history} />
            </div>

            <div style={{ marginBottom: 4 }}><SectionLabel>BREAKDOWN</SectionLabel></div>
            <MetricBar label="CYCLOMATIC COMPLEXITY" score={scan.complexityScore} desc="Chemins d'exécution indépendants. Élevé = difficile à tester." rawLabel="max cx" rawValue={scan.rawComplexity} />
            <MetricBar label="COGNITIVE COMPLEXITY"  score={scan.cognitiveComplexityScore ?? 0} desc="Charge mentale réelle (imbrication pénalisée). Mesure ce qu'un humain ressent en lisant le code." rawLabel="max cog" rawValue={scan.rawCognitiveComplexity ?? 0} />
            <MetricBar label="FUNCTION SIZE"         score={scan.functionSizeScore} desc="Taille de la plus grosse fonction (lignes). Les grandes fonctions font souvent trop de choses." rawLabel="max lines" rawValue={scan.rawFunctionSize} />
            <MetricBar label="CHURN"                 score={scan.churnScore} desc="Fréquence de modification sur 30 jours (commits git). Un fort churn révèle une zone instable." rawLabel="commits" rawValue={scan.rawChurn} />
            <MetricBar label="NESTING DEPTH"         score={scan.depthScore} desc="Niveau d'imbrication maximal (if/for/while). Le code profond est difficile à lire et déboguer." rawLabel="max depth" rawValue={scan.rawDepth} />
            <MetricBar label="PARAMETERS"            score={scan.paramScore} desc="Nombre max de paramètres dans une fonction. Trop de paramètres signale un problème d'encapsulation." rawLabel="max params" rawValue={scan.rawParams} />

            {/* Couplage : used by / uses */}
            {(() => {
              const usedBy = scan.fanIn;
              const uses   = scan.fanOut;
              const usedByColor = usedBy > 10 ? '#ef4444' : usedBy > 5 ? '#f97316' : '#4a4a52';
              const usesColor   = uses   > 10 ? '#ef4444' : uses   > 5 ? '#f97316' : '#4a4a52';
              return (
                <div style={{ padding: '9px 0', borderBottom: '1px solid #111113' }}>
                  <div style={{ marginBottom: 6 }}><SectionLabel>COUPLING</SectionLabel></div>
                  <div style={{ display: 'flex', gap: 12, marginBottom: 6 }}>
                    <div style={{ flex: 1, background: '#0d0d0f', borderRadius: 3, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#4a4a52', letterSpacing: '0.08em', marginBottom: 4 }}>USED BY</div>
                      <div style={{ fontSize: 18, fontWeight: 300, color: usedByColor, lineHeight: 1, marginBottom: 3 }}>{usedBy}</div>
                      <div style={{ fontSize: 9, color: '#3a3a44', lineHeight: 1.4 }}>
                        {usedBy === 0 ? 'not imported anywhere' : `${usedBy} file${usedBy > 1 ? 's' : ''} import this`}
                      </div>
                    </div>
                    <div style={{ flex: 1, background: '#0d0d0f', borderRadius: 3, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#4a4a52', letterSpacing: '0.08em', marginBottom: 4 }}>USES</div>
                      <div style={{ fontSize: 18, fontWeight: 300, color: usesColor, lineHeight: 1, marginBottom: 3 }}>{uses}</div>
                      <div style={{ fontSize: 9, color: '#3a3a44', lineHeight: 1.4 }}>
                        {uses === 0 ? 'no dependencies' : `imports ${uses} other file${uses > 1 ? 's' : ''}`}
                      </div>
                    </div>
                  </div>
                  {usedBy > 5 && (
                    <div style={{ fontSize: 9, color: usedBy > 10 ? '#6a2a2a' : '#6a4a2a', lineHeight: 1.5 }}>
                      ⚠ widely imported — changes here may affect {usedBy} other files
                    </div>
                  )}
                  {uses > 5 && (
                    <div style={{ fontSize: 9, color: uses > 10 ? '#6a2a2a' : '#6a4a2a', lineHeight: 1.5 }}>
                      ⚠ high dependency — bugs in {uses} other files may propagate here
                    </div>
                  )}
                </div>
              );
            })()}

            {scan.hotspotScore > 0 && (
              <div style={{ padding: '9px 0', borderBottom: '1px solid #111113' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: '#8a8a94', letterSpacing: '0.08em', fontWeight: 600 }}>HOTSPOT</span>
                  <span style={{ fontSize: 12, color: scan.hotspotScore >= 60 ? '#ef4444' : scan.hotspotScore >= 20 ? '#f97316' : '#eab308', fontWeight: 600 }}>
                    {scan.hotspotScore.toFixed(1)}
                  </span>
                </div>
                <div style={{ height: 2, background: '#1a1a1e', borderRadius: 1, marginBottom: 5, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(100, (scan.hotspotScore / 150) * 100)}%`, background: scan.hotspotScore >= 60 ? '#ef4444' : '#f97316', borderRadius: 1, transition: 'width 0.4s ease' }} />
                </div>
                <div style={{ fontSize: 9, color: '#4a4a52', lineHeight: 1.55 }}>
                  Composite risk · complexity × churn. Élevé = zone instable et difficile.
                  <span style={{ color: '#3a3a42', marginLeft: 5 }}>· max 150</span>
                </div>
              </div>
            )}

            <div style={{ padding: '7px 0', borderBottom: '1px solid #111113', display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 10, color: '#8a8a94', letterSpacing: '0.08em', fontWeight: 600 }}>LANGUAGE</span>
              <span style={{ fontSize: 10, color: '#4a4a52' }}>{scan.language}</span>
            </div>

            {functions.filter(fn => fn.name !== 'anonymous').length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div style={{ marginBottom: 8 }}><SectionLabel>FUNCTIONS</SectionLabel></div>
                {functions.filter(fn => fn.name !== 'anonymous').map(fn => (
                  <div key={fn.name + fn.start_line} style={{ padding: '6px 0', borderBottom: '1px solid #111113' }}>
                    <div style={{ fontSize: 11, color: '#a0a0a8' }}>{fn.name}</div>
                    <div style={{ display: 'flex', gap: 10, fontSize: 10, marginTop: 2 }}>
                      <span style={{ color: '#4a4a52' }}>l.{fn.start_line}</span>
                      <span style={{ color: '#4a4a52' }}>{fn.line_count}L</span>
                      <span style={{ color: fn.cyclomatic_complexity > 10 ? '#ef4444' : fn.cyclomatic_complexity > 5 ? '#f97316' : '#4a4a52' }}>cx:{fn.cyclomatic_complexity}</span>
                      <span style={{ color: (fn.cognitive_complexity ?? 0) > 20 ? '#ef4444' : (fn.cognitive_complexity ?? 0) > 10 ? '#f97316' : '#4a4a52' }}>cog:{fn.cognitive_complexity ?? 0}</span>
                      <span style={{ color: fn.parameter_count > 5 ? '#ef4444' : '#4a4a52' }}>p:{fn.parameter_count}</span>
                      <span style={{ color: fn.max_depth > 4 ? '#ef4444' : fn.max_depth > 2 ? '#f97316' : '#4a4a52' }}>d:{fn.max_depth}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {activeTab === 'memory' && (
          <>
            {memories.length === 0 ? (
              <div style={{ color: '#3a3a44', fontSize: 11, marginTop: 8, lineHeight: 1.7 }}>
                No memory notes for this file yet.<br/>
                Notes are generated automatically after a few scans and interactions.
              </div>
            ) : memories.map(note => {
              const typeColor: Record<string, string> = { insight: '#4a9eff', warning: '#f97316', fix: '#22c55e', pattern: '#a78bfa' };
              const typeIcon:  Record<string, string> = { insight: '◆', warning: '⚠', fix: '✓', pattern: '➳' };
              const typeLabel: Record<string, string> = { insight: 'INSIGHT', warning: 'WARNING', fix: 'FIX', pattern: 'PATTERN' };
              const color = typeColor[note.type] ?? '#4a4a52';
              const ago = (() => {
                const ms = Date.now() - new Date(note.updatedAt).getTime();
                const d  = Math.floor(ms / 86400000);
                const h  = Math.floor(ms / 3600000);
                return d > 0 ? `${d}d ago` : h > 0 ? `${h}h ago` : 'just now';
              })();
              return (
                <div key={note.id} style={{ padding: '10px 0', borderBottom: '1px solid #111113' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                    <span style={{ color, fontSize: 11 }}>{typeIcon[note.type]}</span>
                    <span style={{ fontSize: 9, color, letterSpacing: '0.1em', fontWeight: 700 }}>{typeLabel[note.type]}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 9, color: '#2a2a32' }}>{ago}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#7a7a82', lineHeight: 1.6 }}>{note.content}</div>
                  {note.links.length > 0 && (
                    <div style={{ fontSize: 9, color: '#2a2a32', marginTop: 4 }}>
                      → {note.links.length} linked insight{note.links.length > 1 ? 's' : ''}
                    </div>
                  )}
                  <button
                    onClick={() => { window.api.dismissMemory(note.id); setMemories(prev => prev.filter(n => n.id !== note.id)); }}
                    style={{ marginTop: 5, fontSize: 9, color: '#2a2a32', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0, transition: 'color 0.15s' }}
                    onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                    onMouseLeave={e => e.currentTarget.style.color = '#2a2a32'}
                  >dismiss</button>
                </div>
              );
            })}
          </>
        )}

        {activeTab === 'analyse' && (
          <>
            {!llmLoading && (
              <div style={{ marginBottom: 14 }}>
                <button onClick={handleExplore} style={{ width: '100%', padding: '7px 0', borderRadius: 2, fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', cursor: 'pointer', border: '1px solid #f97316', background: 'transparent', color: '#f97316', fontFamily: 'monospace', transition: 'all 0.15s' }}>
                  {llmResponse ? '↺ RE-ANALYZE' : '▶ EXPLORE'}
                </button>
                {llmFromCache && (
                  <div style={{ fontSize: 9, color: '#2a2a32', textAlign: 'center', marginTop: 5, letterSpacing: '0.06em' }}>
                    ✓ saved analysis · re-analyze to refresh
                  </div>
                )}
              </div>
            )}
            {llmThinking && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#4a4a52', fontSize: 11, margin: '8px 0' }}>
                <span style={{ animation: 'pulse-spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
                <span>Pulse réfléchit<span style={{ animation: 'pulse-dots 1.4s steps(3, end) infinite' }}>...</span></span>
              </div>
            )}
            {llmLoading && !llmThinking && (
              <div style={{ fontSize: 9, color: '#3a3a44', marginBottom: 8, letterSpacing: '0.08em' }}>▌ génération en cours</div>
            )}
            {llmResponse && (
              <div className="pulse-llm" style={{ fontSize: 11, lineHeight: 1.65 }}
                dangerouslySetInnerHTML={{ __html: marked(llmResponse) as string }}
              />
            )}
            {!llmResponse && !llmLoading && (
              <div style={{ color: '#3a3a44', fontSize: 11, marginTop: 8, lineHeight: 1.7 }}>
                Aucune analyse pour ce fichier.<br/>
                Cliquez sur <span style={{ color: '#f97316' }}>▶ EXPLORE</span> pour lancer.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
