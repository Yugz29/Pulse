import { useState, useEffect, useRef, useCallback } from 'react';
import type { AppSettings } from '../types';

// ── Types ──────────────────────────────────────────────────────────────────
type ConnStatus = 'idle' | 'fetching' | 'ok' | 'error';

const PERSPECTIVE_URL = 'http://127.0.0.1:11435';

const ROLES: { key: 'analyzer' | 'coder' | 'brainstorm' | 'fast'; modelKey: keyof AppSettings; label: string; hint: string }[] = [
  { key: 'analyzer',   modelKey: 'modelAnalyzer',   label: 'ANALYZER',   hint: 'file quality' },
  { key: 'fast',       modelKey: 'modelFast',       label: 'FAST',       hint: 'error triage · memory' },
  { key: 'brainstorm', modelKey: 'modelBrainstorm', label: 'BRAINSTORM', hint: 'intel & architecture' },
  { key: 'coder',      modelKey: 'modelCoder',      label: 'CODER',      hint: 'code generation' },
];

// ── ModelSelect défini HORS du composant parent pour éviter les remounts ──
interface ModelSelectProps {
  value: string;
  onChange: (val: string) => void;
  ollamaModels: string[];
  perspModels: string[];
  includeGeneral?: boolean;
  placeholder?: string;
}

function ModelSelect({ value, onChange, ollamaModels, perspModels, includeGeneral, placeholder }: ModelSelectProps) {
  const allModels = [...ollamaModels, ...perspModels];
  const inp: React.CSSProperties = {
    flex: 1, background: '#0d0d0f', border: '1px solid #1e1e22',
    borderRadius: 2, padding: '5px 8px', fontSize: 11, color: '#c0c0c8',
    fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box',
  };
  const sel: React.CSSProperties = {
    ...inp, cursor: 'pointer', appearance: 'none' as any, width: '100%',
  };

  if (allModels.length === 0) {
    return (
      <input
        style={inp}
        value={value}
        onChange={e => onChange(e.target.value)}
        spellCheck={false}
        placeholder={placeholder ?? 'e.g. pulse-qwen3'}
      />
    );
  }

  return (
    <div style={{ position: 'relative', flex: 1 }}>
      <select style={sel} value={value} onChange={e => onChange(e.target.value)}>
        {includeGeneral
          ? <option value="">← use general model</option>
          : <option value="">— pick a model —</option>
        }
        {ollamaModels.length > 0 && (
          <optgroup label="OLLAMA">
            {ollamaModels.map(m => <option key={m} value={m}>{m}</option>)}
          </optgroup>
        )}
        {perspModels.length > 0 && (
          <optgroup label="PERSPECTIVE · Apple Intelligence">
            {perspModels.map(m => <option key={m} value={m}>{m}</option>)}
          </optgroup>
        )}
      </select>
      <span style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', color: '#4a4a52', fontSize: 9, pointerEvents: 'none' }}>▾</span>
    </div>
  );
}

// ── StatusBadge défini HORS du composant parent ────────────────────────────
function StatusBadge({ status, count }: { status: ConnStatus; count: number }) {
  if (status === 'idle')     return null;
  if (status === 'fetching') return <span style={{ fontSize: 9, color: '#f97316' }}>fetching…</span>;
  if (status === 'error')    return <span style={{ fontSize: 9, color: '#6a2a2a' }}>unreachable</span>;
  return <span style={{ fontSize: 9, color: '#22c55e' }}>● {count} models</span>;
}

// ── SettingsPanel ──────────────────────────────────────────────────────────
const EMPTY_FORM: AppSettings = {
  model: 'pulse-qwen3', baseUrl: 'http://localhost:11434', modelGeneral: 'pulse-qwen3',
  modelAnalyzer: '', modelCoder: '', modelBrainstorm: '', modelFast: '',
  baseUrlFast: '', baseUrlAnalyzer: '', perspectiveUrl: PERSPECTIVE_URL, serverForRole: {},
};

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [form,    setForm]    = useState<AppSettings>(EMPTY_FORM);
  const [saved,   setSaved]   = useState(false);
  const [loading, setLoading] = useState(true);

  const [ollamaStatus,   setOllamaStatus]   = useState<ConnStatus>('idle');
  const [perspStatus,    setPerspStatus]    = useState<ConnStatus>('idle');
  const [ollamaModels,   setOllamaModels]   = useState<string[]>([]);
  const [perspModels,    setPerspModels]    = useState<string[]>([]);

  const ollamaTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    window.api.getSettings().then(s => {
      setForm({ ...EMPTY_FORM, ...s, perspectiveUrl: PERSPECTIVE_URL });
      setLoading(false);
      // Fetch Perspective models au chargement (URL fixe)
      setOllamaStatus('fetching');
      window.api.getAvailableModels(s.baseUrl || EMPTY_FORM.baseUrl, 'ollama').then(res => {
        if (res.models.length > 0) { setOllamaModels(res.models); setOllamaStatus('ok'); }
        else setOllamaStatus('error');
      });
      setPerspStatus('fetching');
      window.api.getAvailableModels(PERSPECTIVE_URL, 'perspective').then(res => {
        if (res.models.length > 0) { setPerspModels(res.models); setPerspStatus('ok'); }
        else setPerspStatus('error');
      });
    }).catch(() => setLoading(false));
  }, []);

  // ── Auto-fetch Ollama sur changement d'URL ─────────────────────────────
  const doFetchOllama = useCallback(async (url: string) => {
    if (!url) { setOllamaStatus('idle'); setOllamaModels([]); return; }
    setOllamaStatus('fetching');
    const res = await window.api.getAvailableModels(url, 'ollama');
    if (res.models.length > 0) { setOllamaModels(res.models); setOllamaStatus('ok'); }
    else { setOllamaModels([]); setOllamaStatus('error'); }
  }, []);

  function handleOllamaUrlChange(url: string) {
    setForm(f => ({ ...f, baseUrl: url }));
    if (ollamaTimer.current) clearTimeout(ollamaTimer.current);
    ollamaTimer.current = setTimeout(() => doFetchOllama(url), 800);
  }

  // ── Role model change ──────────────────────────────────────────────────
  function setRoleValue(role: 'analyzer' | 'coder' | 'brainstorm' | 'fast', modelKey: keyof AppSettings, value: string) {
    const server: 'primary' | 'perspective' | undefined =
      ollamaModels.includes(value) ? 'primary' :
      perspModels.includes(value)  ? 'perspective' :
      value === ''                 ? undefined : 'primary';

    setForm(f => ({
      ...f,
      [modelKey]: value,
      serverForRole: { ...f.serverForRole, [role]: server },
    }));
  }

  // ── Save ───────────────────────────────────────────────────────────────
  async function handleSave() {
    const sfr = form.serverForRole ?? {};
    const derived: AppSettings = {
      ...form,
      perspectiveUrl:  PERSPECTIVE_URL,
      baseUrlFast:     sfr.fast     === 'perspective' ? PERSPECTIVE_URL : '',
      baseUrlAnalyzer: sfr.analyzer === 'perspective' ? PERSPECTIVE_URL : '',
    };
    await window.api.saveSettings(derived);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  // ── Styles ─────────────────────────────────────────────────────────────
  const inp = (extra?: React.CSSProperties): React.CSSProperties => ({
    flex: 1, background: '#0d0d0f', border: '1px solid #1e1e22', borderRadius: 2,
    padding: '5px 8px', fontSize: 11, color: '#c0c0c8', fontFamily: 'monospace',
    outline: 'none', boxSizing: 'border-box', ...extra,
  });

  // ── Status inline ──────────────────────────────────────────────────────
  function StatusBadge({ status, count }: { status: ConnStatus; count: number }) {
    if (status === 'idle')     return null;
    if (status === 'fetching') return <span style={{ fontSize: 9, color: '#f97316' }}>fetching…</span>;
    if (status === 'error')    return <span style={{ fontSize: 9, color: '#6a2a2a' }}>unreachable</span>;
    return <span style={{ fontSize: 9, color: '#22c55e' }}>● {count} models</span>;
  }

  const sfr = form.serverForRole ?? {};

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 100, background: '#0a0a0c', display: 'flex', flexDirection: 'column', fontFamily: 'monospace' }}>

      {/* Header */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid #1e1e22', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <span style={{ fontSize: 10, letterSpacing: '0.14em', color: '#6a6a72', fontWeight: 700 }}>SETTINGS</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4a4a52', fontSize: 18, padding: 0, lineHeight: 1 }}>×</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
        {loading ? <div style={{ color: '#4a4a52', fontSize: 11 }}>Loading…</div> : (
          <>
            {/* ── SERVERS ─────────────────────────────────────────────── */}
            <div style={{ fontSize: 9, letterSpacing: '0.14em', color: '#3a3a44', marginBottom: 10 }}>SERVERS</div>

            {/* Ollama */}
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                <span style={{ fontSize: 9, color: '#6a6a72', letterSpacing: '0.1em', minWidth: 80 }}>OLLAMA</span>
                <StatusBadge status={ollamaStatus} count={ollamaModels.length} />
              </div>
              <input
                style={inp()}
                value={form.baseUrl}
                onChange={e => handleOllamaUrlChange(e.target.value)}
                spellCheck={false}
                placeholder="http://localhost:11434"
              />
            </div>

            {/* Perspective (URL + modèle fixes) */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 9, color: '#6a6a72', letterSpacing: '0.1em', minWidth: 80 }}>PERSPECTIVE</span>
                <span style={{ fontSize: 9, color: '#2a2a32' }}>{PERSPECTIVE_URL} · <span style={{ color: '#3a5a7a' }}>apple.local</span></span>
                <StatusBadge status={perspStatus} count={perspModels.length} />
              </div>
            </div>

            {/* ── MODELS ──────────────────────────────────────────────── */}
            <div style={{ borderTop: '1px solid #111113', paddingTop: 16, marginBottom: 10 }}>
              <div style={{ fontSize: 9, letterSpacing: '0.14em', color: '#3a3a44', marginBottom: 12 }}>MODELS</div>

              {/* General */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <span style={{ fontSize: 9, color: '#a0a0a8', letterSpacing: '0.1em', minWidth: 80, flexShrink: 0 }}>GENERAL</span>
                <ModelSelect
                  value={form.modelGeneral}
                  onChange={v => setForm(f => ({ ...f, modelGeneral: v }))}
                  ollamaModels={ollamaModels}
                  perspModels={perspModels}
                  placeholder="e.g. pulse-qwen3"
                />
              </div>

              {/* Role overrides */}
              <div style={{ borderTop: '1px solid #0e0e10', paddingTop: 10 }}>
                {ROLES.map(({ key, modelKey, label, hint }) => {
                  const val     = (form[modelKey] as string) ?? '';
                  const isPersp = sfr[key] === 'perspective' && !!val;
                  return (
                    <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <div style={{ minWidth: 80, flexShrink: 0 }}>
                        <div style={{ fontSize: 9, color: '#5a5a62', letterSpacing: '0.08em' }}>{label}</div>
                        <div style={{ fontSize: 8, color: '#2a2a32', marginTop: 1 }}>{hint}</div>
                      </div>
                      <ModelSelect
                        value={val}
                        onChange={v => setRoleValue(key, modelKey, v)}
                        ollamaModels={ollamaModels}
                        perspModels={perspModels}
                        includeGeneral
                      />
                      {isPersp && (
                        <span style={{ fontSize: 8, color: '#3a5a7a', flexShrink: 0 }}>⚡</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Footer */}
      <div style={{ padding: '12px 20px', borderTop: '1px solid #1e1e22', display: 'flex', justifyContent: 'flex-end', gap: 8, flexShrink: 0 }}>
        <button onClick={onClose} style={{ background: 'none', border: '1px solid #1e1e22', borderRadius: 2, padding: '5px 14px', fontSize: 10, color: '#4a4a52', cursor: 'pointer', fontFamily: 'monospace' }}>CANCEL</button>
        <button onClick={handleSave} style={{ background: saved ? '#14532d' : '#1e1e22', border: `1px solid ${saved ? '#22c55e' : '#2e2e36'}`, borderRadius: 2, padding: '5px 14px', fontSize: 10, color: saved ? '#22c55e' : '#a0a0a8', cursor: 'pointer', fontFamily: 'monospace', transition: 'all 0.2s' }}>
          {saved ? '✓ SAVED' : 'SAVE'}
        </button>
      </div>
    </div>
  );
}
