import { useState, useEffect } from 'react';
import type { AppSettings } from '../types';

const ROLE_OVERRIDES: { key: keyof AppSettings; label: string; hint: string }[] = [
  { key: 'modelAnalyzer',   label: 'ANALYZER',   hint: 'explore button (file quality)' },
  { key: 'modelCoder',      label: 'CODER',      hint: 'agent V2 — code generation' },
  { key: 'modelBrainstorm', label: 'BRAINSTORM', hint: 'ideas & architecture' },
  { key: 'modelFast',       label: 'FAST',       hint: 'error triage, quick answers' },
];

const EMPTY_FORM: AppSettings = {
  model:           'pulse-qwen3',
  baseUrl:         'http://localhost:11434',
  modelGeneral:    'pulse-qwen3',
  modelAnalyzer:   '',
  modelCoder:      '',
  modelBrainstorm: '',
  modelFast:       '',
};

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [form,    setForm]    = useState<AppSettings>(EMPTY_FORM);
  const [saved,   setSaved]   = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    window.api.getSettings().then(s => {
      setForm({ ...EMPTY_FORM, ...s });
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    await window.api.saveSettings(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const inp = (extra?: React.CSSProperties): React.CSSProperties => ({
    width: '100%', background: '#0d0d0f', border: '1px solid #1e1e22',
    borderRadius: 2, padding: '5px 8px', fontSize: 11, color: '#c0c0c8',
    fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box', ...extra,
  });

  const lbl = (extra?: React.CSSProperties): React.CSSProperties => ({
    fontSize: 9, letterSpacing: '0.1em', color: '#4a4a52', marginBottom: 4,
    display: 'block', ...extra,
  });

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 100,
      background: '#0a0a0c', display: 'flex', flexDirection: 'column',
      fontFamily: 'monospace',
    }}>
      {/* Header */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid #1e1e22', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <span style={{ fontSize: 10, letterSpacing: '0.14em', color: '#6a6a72', fontWeight: 700 }}>SETTINGS</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4a4a52', fontSize: 18, padding: 0, lineHeight: 1 }}>×</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
        {loading ? <div style={{ color: '#4a4a52', fontSize: 11 }}>Loading…</div> : (
          <>
            <div style={{ marginBottom: 20 }}>
              <span style={lbl({ color: '#6a6a72' })}>OLLAMA BASE URL</span>
              <input style={inp()} value={form.baseUrl} onChange={e => setForm(f => ({ ...f, baseUrl: e.target.value }))} spellCheck={false} />
            </div>

            <div style={{ borderTop: '1px solid #111113', marginBottom: 20 }} />

            <div style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                <span style={lbl({ margin: 0, color: '#a0a0a8', letterSpacing: '0.14em' })}>GENERAL MODEL</span>
                <span style={{ fontSize: 9, color: '#4a4a52' }}>used for all roles unless overridden</span>
              </div>
              <input
                style={inp({ borderColor: '#2e2e3e', color: '#d0d0d8' })}
                value={form.modelGeneral}
                onChange={e => setForm(f => ({ ...f, modelGeneral: e.target.value }))}
                spellCheck={false}
                placeholder="e.g. pulse-qwen3"
              />
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
              {[
                { label: 'qwen3 (recommended)', model: 'pulse-qwen3' },
                { label: 'dolphin',             model: 'pulse-dolphin' },
                { label: 'fast',                model: 'pulse-fast' },
              ].map(p => (
                <button key={p.model} onClick={() => setForm(f => ({ ...f, modelGeneral: p.model }))}
                  style={{ background: form.modelGeneral === p.model ? '#1e2a3a' : '#111113', border: `1px solid ${form.modelGeneral === p.model ? '#4a9eff44' : '#1e1e22'}`, borderRadius: 2, padding: '3px 10px', fontSize: 10, color: form.modelGeneral === p.model ? '#4a9eff' : '#5a5a62', cursor: 'pointer', fontFamily: 'monospace' }}>
                  {p.label}
                </button>
              ))}
            </div>

            <div style={{ borderTop: '1px solid #111113', paddingTop: 20, marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
                <span style={{ fontSize: 9, letterSpacing: '0.14em', color: '#3a3a44' }}>ROLE OVERRIDES</span>
                <span style={{ fontSize: 9, color: '#2a2a32' }}>leave empty to use general model</span>
              </div>
              {ROLE_OVERRIDES.map(({ key, label, hint }) => (
                <div key={key} style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={lbl({ margin: 0, color: '#4a4a52' })}>{label}</span>
                    <span style={{ fontSize: 9, color: '#252530' }}>{hint}</span>
                  </div>
                  <input
                    style={inp({ color: '#6a6a72' })}
                    value={form[key] as string}
                    onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                    spellCheck={false}
                    placeholder={`defaults to ${form.modelGeneral || 'general model'}`}
                  />
                </div>
              ))}
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
