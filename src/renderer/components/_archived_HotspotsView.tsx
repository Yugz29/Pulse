import { useState, useEffect } from 'react';
import type { HotspotRow, Scan } from '../types';
import { scoreColor, classifyLayer, LAYER_LABELS, LAYER_COLORS } from '../utils';

interface Props {
  onSelect: (s: Scan | null) => void;
  scans: Scan[];
}

function hotspotLabel(score: number): { label: string; color: string } {
  if (score >= 40) return { label: 'CRITICAL', color: '#ef4444' };
  if (score >= 20) return { label: 'FRAGILE',  color: '#f97316' };
  if (score >= 8)  return { label: 'WATCH',    color: '#eab308' };
  return              { label: 'STABLE',   color: '#22c55e' };
}

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div style={{ height: 2, background: '#1a1a1e', borderRadius: 1, overflow: 'hidden', marginTop: 3 }}>
      <div style={{ height: '100%', width: `${Math.min(100, (value / (max || 1)) * 100)}%`, background: color, borderRadius: 1, transition: 'width 0.4s ease' }} />
    </div>
  );
}

// Chemin relatif lisible : garde les 3 derniers segments
function shortPath(filePath: string): { file: string; dir: string; full: string } {
  const parts = filePath.split('/');
  const file  = parts[parts.length - 1] ?? filePath;
  const dir   = parts.slice(-4, -1).join('/');
  // Cherche src/ comme racine relative si possible
  const srcIdx = parts.indexOf('src');
  const full   = srcIdx >= 0 ? parts.slice(srcIdx).join('/') : parts.slice(-4).join('/');
  return { file, dir, full };
}

export default function HotspotsView({ onSelect, scans }: Props) {
  const [hotspots,      setHotspots]      = useState<HotspotRow[]>([]);
  const [complexStable, setComplexStable] = useState<HotspotRow[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [activeTab,     setActiveTab]     = useState<'hotspots' | 'stable'>('hotspots');

  useEffect(() => {
    setLoading(true);
    Promise.all([
      window.api.getHotspots(),
      window.api.getComplexStable(),
    ]).then(([h, cs]) => {
      const map = (r: any): HotspotRow => ({
        filePath:        r.file_path,
        globalScore:     r.global_score,
        complexityScore: r.complexity_score,
        churnScore:      r.churn_score,
        fanIn:           r.fan_in,
        language:        r.language,
        hotspotScore:    r.hotspot_score,
        scannedAt:       r.scanned_at,
      });
      setHotspots(h.map(map));
      setComplexStable(cs.map(map));
      setLoading(false);
    });
  }, [scans]);

  const rows       = activeTab === 'hotspots' ? hotspots : complexStable;
  const maxScore   = Math.max(...rows.map(r => r.hotspotScore), 1);
  const scanMap    = new Map(scans.map(s => [s.filePath, s]));

  const tabStyle = (t: 'hotspots' | 'stable'): React.CSSProperties => ({
    fontSize: 9, letterSpacing: '0.14em', fontWeight: 700,
    padding: '6px 16px', cursor: 'pointer', border: 'none',
    background: 'transparent', fontFamily: 'monospace',
    color: activeTab === t ? '#d0d0d8' : '#3a3a44',
    borderBottom: activeTab === t ? '1px solid #4a9eff' : '1px solid transparent',
    transition: 'color 0.15s',
  });

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '20px 40px 0', flexShrink: 0, borderBottom: '1px solid #1e1e22' }}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8ea', marginBottom: 4 }}>Hotspots</div>
          <div style={{ fontSize: 11, color: '#4a4a52', lineHeight: 1.6 }}>
            Where bugs are most likely to appear.
            <span style={{ color: '#3a3a44', marginLeft: 8 }}>score = risk × churn / 100</span>
          </div>
        </div>

        {!loading && hotspots.length > 0 && (
          <div style={{ display: 'flex', gap: 32, marginBottom: 16 }}>
            {[
              { label: 'CRITICAL', value: hotspots.filter(h => h.hotspotScore >= 40).length, color: '#ef4444' },
              { label: 'FRAGILE',  value: hotspots.filter(h => h.hotspotScore >= 20 && h.hotspotScore < 40).length, color: '#f97316' },
              { label: 'WATCH',    value: hotspots.filter(h => h.hotspotScore >= 8  && h.hotspotScore < 20).length, color: '#eab308' },
              { label: 'STABLE*',  value: complexStable.length, color: '#4a4a52' },
            ].map(s => (
              <div key={s.label}>
                <div style={{ fontSize: 9, color: '#4a4a52', letterSpacing: '0.1em', marginBottom: 2 }}>{s.label}</div>
                <div style={{ fontSize: 22, fontWeight: 300, color: s.color, lineHeight: 1 }}>{s.value}</div>
              </div>
            ))}
            <div style={{ marginLeft: 'auto', fontSize: 9, color: '#2e2e34', alignSelf: 'flex-end', paddingBottom: 2 }}>
              * complex but untouched
            </div>
          </div>
        )}

        <div style={{ display: 'flex', marginLeft: -40, paddingLeft: 40 }}>
          <button style={tabStyle('hotspots')} onClick={() => setActiveTab('hotspots')}>HOTSPOTS</button>
          <button style={tabStyle('stable')}   onClick={() => setActiveTab('stable')}>COMPLEX · STABLE</button>
        </div>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading && (
          <div style={{ padding: '40px', color: '#4a4a52', fontSize: 11, fontFamily: 'monospace' }}>Loading…</div>
        )}

        {!loading && rows.length === 0 && (
          <div style={{ padding: '40px', color: '#4a4a52', fontSize: 11, fontFamily: 'monospace', lineHeight: 1.8 }}>
            {activeTab === 'hotspots'
              ? 'No hotspots detected.\nFiles need git churn data (commits in last 30 days) to compute hotspot score.'
              : 'No complex-but-stable files detected.'}
          </div>
        )}

        {!loading && rows.map((row, i) => {
          const badge    = hotspotLabel(row.hotspotScore);
          const scan     = scanMap.get(row.filePath);
          const path     = shortPath(row.filePath);
          const layer    = classifyLayer(row.filePath);

          return (
            <div
              key={row.filePath}
              onClick={() => scan && onSelect(scan)}
              style={{ padding: '13px 40px', borderBottom: '1px solid #0d0d0f', cursor: scan ? 'pointer' : 'default', transition: 'background 0.1s' }}
              onMouseEnter={e => { e.currentTarget.style.background = '#0d0d0f'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              {/* Row 1 : rank · filename · layer · badge · score */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <span style={{ fontSize: 10, color: '#2e2e34', minWidth: 18, fontFamily: 'monospace', flexShrink: 0 }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#d0d0d8', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
                    {path.file}
                  </div>
                  <div style={{ fontSize: 9, color: '#3a3a40', marginTop: 1, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {path.full}
                  </div>
                </div>
                <span style={{ fontSize: 9, letterSpacing: '0.1em', color: LAYER_COLORS[layer], border: `1px solid ${LAYER_COLORS[layer]}33`, borderRadius: 2, padding: '1px 6px', fontFamily: 'monospace', flexShrink: 0 }}>
                  {LAYER_LABELS[layer]}
                </span>
                <span style={{ fontSize: 9, letterSpacing: '0.1em', color: badge.color, border: `1px solid ${badge.color}44`, borderRadius: 2, padding: '1px 6px', fontFamily: 'monospace', fontWeight: 700, flexShrink: 0 }}>
                  {badge.label}
                </span>
                <span style={{ fontSize: 18, fontWeight: 300, color: badge.color, lineHeight: 1, minWidth: 40, textAlign: 'right', fontFamily: 'monospace', flexShrink: 0 }}>
                  {row.hotspotScore.toFixed(1)}
                </span>
              </div>

              {/* Score bar */}
              <Bar value={row.hotspotScore} max={maxScore} color={badge.color} />

              {/* Row 2 : metrics */}
              <div style={{ display: 'flex', gap: 20, marginTop: 7 }}>
                {[
                  { label: 'risk',       value: row.globalScore.toFixed(0),    color: scoreColor(row.globalScore) },
                  { label: 'complexity', value: row.complexityScore.toFixed(0), color: row.complexityScore >= 50 ? '#ef4444' : '#5a5a62' },
                  { label: 'churn',      value: row.churnScore.toFixed(0),      color: row.churnScore      >= 50 ? '#ef4444' : '#5a5a62' },
                  { label: 'fan-in',     value: String(row.fanIn),              color: row.fanIn > 10 ? '#f97316' : '#5a5a62' },
                  { label: 'lang',       value: row.language,                   color: '#3a3a42' },
                ].map(m => (
                  <div key={m.label} style={{ display: 'flex', gap: 4, alignItems: 'baseline' }}>
                    <span style={{ fontSize: 9, color: '#3a3a42', letterSpacing: '0.08em' }}>{m.label}</span>
                    <span style={{ fontSize: 11, color: m.color, fontFamily: 'monospace' }}>{m.value}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
