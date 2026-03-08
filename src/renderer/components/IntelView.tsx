import { useState, useEffect, useRef } from 'react';
import { marked } from 'marked';
import type { Scan, Edge, IntelMessage } from '../types';
import { LLM_STYLES } from '../utils';

const INTEL_QUICK_PROMPTS = [
  'Quels fichiers dois-je refactoriser en priorité ?',
  'Pourquoi le projet se dégrade-t-il ?',
  'Analyse les risques architecturaux.',
  'Quels modules sont les plus dangereux à modifier ?',
];

interface Props {
  scans: Scan[];
  edges: Edge[];
  projectHistory: { date: string; score: number }[];
  projectPath: string;
  selectedFile: Scan | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

export default function IntelView({ scans, edges, projectHistory, projectPath, selectedFile, inputRef }: Props) {
  const [messages, setMessages] = useState<IntelMessage[]>([]);
  const [input,    setInput]    = useState('');
  const [loading,  setLoading]  = useState(false);
  const [thinking, setThinking] = useState(false);
  const scrollRef     = useRef<HTMLDivElement>(null);
  const llmCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => { return () => { llmCleanupRef.current?.(); }; }, []);

  useEffect(() => {
    window.api.getIntelMessages().then(rows => {
      if (rows.length > 0) setMessages(rows);
    });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  function buildCtx() {
    const topScans = [...scans].sort((a, b) => b.globalScore - a.globalScore).slice(0, 10).map(s => ({
      filePath: s.filePath, globalScore: s.globalScore, complexityScore: s.complexityScore,
      functionSizeScore: s.functionSizeScore, churnScore: s.churnScore,
      depthScore: s.depthScore, paramScore: s.paramScore,
      fanIn: s.fanIn, fanOut: s.fanOut, trend: s.trend, language: s.language,
    }));
    const topFanIn  = [...scans].filter(s => s.fanIn > 0).sort((a, b) => b.fanIn - a.fanIn).slice(0, 5).map(s => ({ filePath: s.filePath, fanIn: s.fanIn }));
    const degrading = scans.filter(s => s.trend === '↑').sort((a, b) => b.globalScore - a.globalScore).slice(0, 4).map(s => ({ filePath: s.filePath, globalScore: s.globalScore }));
    return {
      projectPath, allScansCount: scans.length, edgesCount: edges.length,
      distribution: {
        stable:   scans.filter(s => s.globalScore < 20).length,
        stressed: scans.filter(s => s.globalScore >= 20 && s.globalScore < 50).length,
        critical: scans.filter(s => s.globalScore >= 50).length,
      },
      topScans, topFanIn, degrading, projectHistory,
      selectedFile: selectedFile ? { filePath: selectedFile.filePath, globalScore: selectedFile.globalScore } : null,
    };
  }

  function send(msg?: string) {
    const text = (msg ?? input).trim();
    if (!text || loading) return;
    setInput('');

    window.api.saveIntelMessage('user', text);

    const history: IntelMessage[] = [...messages, { role: 'user', content: text }];
    setMessages([...history, { role: 'assistant', content: '', streaming: true }]);
    setLoading(true);
    setThinking(true);

    llmCleanupRef.current?.();
    llmCleanupRef.current = null;

    let accumulated = '';
    const cleanup = () => { offChunk(); offDone(); offErr(); };

    const offChunk = window.api.onLLMChunk(chunk => {
      accumulated += chunk;
      setThinking(false);
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last?.role === 'assistant') return [...prev.slice(0, -1), { ...last, content: last.content + chunk }];
        return prev;
      });
    });
    const offDone = window.api.onLLMDone(() => {
      setLoading(false);
      setThinking(false);
      if (accumulated) window.api.saveIntelMessage('assistant', accumulated);
      setMessages(prev => {
        const last = prev[prev.length - 1];
        return last ? [...prev.slice(0, -1), { ...last, streaming: false }] : prev;
      });
      llmCleanupRef.current = null;
      cleanup();
    });
    const offErr = window.api.onLLMError(err => {
      setLoading(false);
      setThinking(false);
      setMessages(prev => [...prev.slice(0, -1), { role: 'assistant', content: `Erreur : ${err}` }]);
      llmCleanupRef.current = null;
      cleanup();
    });

    llmCleanupRef.current = cleanup;
    window.api.askLLMProject({ ctx: buildCtx(), messages: history });
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <style>{LLM_STYLES}</style>

      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '24px 40px' }}>
        {messages.length === 0 ? (
          <div>
            <div style={{ fontSize: 9, color: '#2e2e34', letterSpacing: '0.14em', marginBottom: 16 }}>SUGGESTED</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7, maxWidth: 520 }}>
              {INTEL_QUICK_PROMPTS.map(q => (
                <button key={q} onClick={() => send(q)} style={{ textAlign: 'left', padding: '9px 14px', borderRadius: 3, border: '1px solid #1a1a1e', background: '#0d0d0f', color: '#6a6a72', fontSize: 11, cursor: 'pointer', fontFamily: 'monospace', transition: 'border-color 0.15s, color 0.15s' }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = '#4a9eff'; e.currentTarget.style.color = '#a0a0a8'; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = '#1a1a1e'; e.currentTarget.style.color = '#6a6a72'; }}
                >
                  {q}
                </button>
              ))}
            </div>
            {selectedFile && (
              <div style={{ marginTop: 20, fontSize: 9, color: '#2e2e34' }}>
                contexte : {selectedFile.filePath.split('/').pop()} sélectionné
              </div>
            )}
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} style={{ marginBottom: 22 }}>
              {msg.role === 'user' ? (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <div style={{ background: '#111113', border: '1px solid #1e1e22', borderRadius: '3px 3px 0 3px', padding: '8px 13px', fontSize: 11, color: '#d0d0d8', maxWidth: '78%', lineHeight: 1.6 }}>
                    {msg.content}
                  </div>
                </div>
              ) : (
                <div style={{ maxWidth: '92%' }}>
                  <div style={{ fontSize: 9, color: '#2e2e34', letterSpacing: '0.12em', marginBottom: 6 }}>PULSE INTEL</div>
                  {msg.streaming && thinking && !msg.content ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#4a4a52', fontSize: 11 }}>
                      <span style={{ animation: 'pulse-spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
                      <span>Pulse réfléchit...</span>
                    </div>
                  ) : (
                    <div className="pulse-llm" style={{ fontSize: 11, lineHeight: 1.65 }}
                      dangerouslySetInnerHTML={{ __html: marked(msg.content || (msg.streaming ? '…' : '')) as string }}
                    />
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div style={{ padding: '10px 40px 18px', borderTop: '1px solid #1a1a1e', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Pose une question sur ton projet…"
            disabled={loading}
            style={{ flex: 1, background: '#0d0d0f', border: '1px solid #1e1e22', borderRadius: 3, padding: '8px 12px', color: '#d0d0d8', fontSize: 11, fontFamily: 'monospace', outline: 'none' }}
          />
          {messages.length > 0 && (
            <button onClick={() => { setMessages([]); window.api.clearIntelMessages(); window.api.abortLLM(); setLoading(false); }}
              style={{ background: 'transparent', border: '1px solid #1e1e22', color: '#4a4a52', fontSize: 9, padding: '7px 10px', borderRadius: 3, cursor: 'pointer', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
              CLEAR
            </button>
          )}
          {loading && (
            <button onClick={() => { window.api.abortLLM(); setLoading(false); }}
              style={{ background: 'transparent', border: '1px solid #ef4444', color: '#ef4444', fontSize: 9, padding: '7px 10px', borderRadius: 3, cursor: 'pointer', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
              STOP
            </button>
          )}
          <button onClick={() => send()} disabled={loading || !input.trim()}
            style={{ background: '#4a9eff', border: '1px solid #4a9eff', color: '#0a0a0b', fontSize: 10, padding: '7px 16px', borderRadius: 3, cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', fontFamily: 'monospace', fontWeight: 700, letterSpacing: '0.1em', opacity: loading || !input.trim() ? 0.4 : 1, transition: 'opacity 0.15s' }}>
            {loading ? '…' : 'SEND'}
          </button>
        </div>
        <div style={{ fontSize: 9, color: '#1e1e22', marginTop: 5 }}>↵ pour envoyer · ⌘K pour focus</div>
      </div>
    </div>
  );
}
