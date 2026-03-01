import { useState, useEffect } from 'react';

interface Scan {
  filePath: string;
  globalScore: number;
  complexityScore: number;
  functionSizeScore: number;
  churnScore: number;
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
}

declare global {
  interface Window {
    api: {
      getScans: () => Promise<Scan[]>;
      getEdges: () => Promise<Edge[]>;
      getFunctions: (filePath: string) => Promise<FunctionDetail[]>;
      onScanComplete: (cb: () => void) => void;
      onEvent: (cb: (e: any) => void) => void;
    };
  }
}

function Detail({ scan, onClose }: { scan: Scan, onClose: () => void }) {
  const color = scan.globalScore >= 50 ? '#ff3b30' : scan.globalScore >= 20 ? '#ff9500' : '#34c759';
  const [functions, setFunctions] = useState<FunctionDetail[]>([]);

  useEffect(() => {
    window.api.getFunctions(scan.filePath).then(setFunctions);
  }, [scan.filePath]);

  return (
    <div style={{ padding: 20, fontSize: 13 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <div style={{ fontWeight: 600 }}>{scan.filePath.split('/').pop()}</div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#86868b', fontSize: 16, lineHeight: 1 }}>×</button>
    </div>
      <div style={{ color: '#86868b', fontSize: 11, marginBottom: 20, wordBreak: 'break-all' }}>{scan.filePath}</div>
      {[
        { label: 'Score global',  value: scan.globalScore.toFixed(1),       color },
        { label: 'Complexité',    value: scan.complexityScore.toFixed(1),    color: '#1d1d1f' },
        { label: 'Taille',        value: scan.functionSizeScore.toFixed(1),  color: '#1d1d1f' },
        { label: 'Churn',         value: scan.churnScore.toFixed(1),         color: '#1d1d1f' },
        { label: 'Langage',       value: scan.language,                      color: '#1d1d1f' },
        { label: 'Trend',         value: scan.trend,                         color: scan.trend === '↑' ? '#ff3b30' : scan.trend === '↓' ? '#34c759' : '#86868b' },
        { label: 'Feedback',      value: scan.feedback ?? '—',               color: '#86868b' },
        { label: 'Scanné le',     value: new Date(scan.scannedAt).toLocaleString(), color: '#86868b' },
      ].map(row => (
        <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
          <span style={{ color: '#86868b' }}>{row.label}</span>
          <span style={{ fontWeight: 500, color: row.color }}>{row.value}</span>
        </div>
      ))}

      {functions.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ color: '#86868b', fontWeight: 500, marginBottom: 8 }}>Fonctions</div>
          {functions.map(fn => (
            <div key={fn.name + fn.start_line} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
              <span style={{ color: '#1d1d1f', fontFamily: 'monospace', fontSize: 12 }}>{fn.name}</span>
              <div style={{ display: 'flex', gap: 10, fontSize: 11 }}>
                <span style={{ color: '#86868b' }}>l.{fn.start_line}</span>
                <span style={{ color: '#86868b' }}>{fn.line_count} lignes</span>
                <span style={{ color: fn.cyclomatic_complexity > 10 ? '#ff3b30' : fn.cyclomatic_complexity > 5 ? '#ff9500' : '#86868b' }}>cx {fn.cyclomatic_complexity}</span>
              </div>
            </div>
          ))}
        </div>
      )}
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
  const [scans, setScans]     = useState<Scan[]>([]);
  const [edges, setEdges]     = useState<Edge[]>([]);
  const [events, setEvents]   = useState<string[]>([]);
  const [selected, setSelected] = useState<Scan | null>(null);

  async function load() {
    const [s, e] = await Promise.all([
      window.api.getScans(),
      window.api.getEdges(),
    ]);
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
        <div style={{ width: 280, borderLeft: '1px solid #e0e0e0', background: '#fff', overflowY: 'auto' }}>
          {selected ? (
            <Detail scan={selected} onClose={() => setSelected(null)}/>
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
