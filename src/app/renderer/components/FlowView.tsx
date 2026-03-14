import type { Scan, Edge } from '../types';
import { scoreColor, classifyLayer, LAYER_LABELS, LAYER_COLORS, LAYER_ORDER, type Layer } from '../utils';

interface Props {
  scans: Scan[];
  edges: Edge[];
  onSelect: (s: Scan | null) => void;
  selectedPath: string | null;
}

export default function FlowView({ scans, edges, onSelect, selectedPath }: Props) {
  const byLayer = new Map<Layer, Scan[]>();
  for (const layer of LAYER_ORDER) byLayer.set(layer, []);
  for (const s of scans) {
    const l = classifyLayer(s.filePath);
    byLayer.get(l)!.push(s);
  }
  for (const [, arr] of byLayer) arr.sort((a, b) => b.globalScore - a.globalScore);

  const activeLayers = LAYER_ORDER.filter(l => (byLayer.get(l)?.length ?? 0) > 0);
  if (!activeLayers.length) {
    return <div style={{ padding: 40, color: '#4a4a52', fontSize: 11 }}>Awaiting scan…</div>;
  }

  const COL_W = 140, COL_GAP = 70, NODE_H = 30, NODE_GAP = 5;
  const H_PAD = 30, V_PAD = 50, HEADER_H = 28;
  const colX = (li: number) => H_PAD + li * (COL_W + COL_GAP);

  const nodePos = new Map<string, { x: number; y: number }>();
  for (let li = 0; li < activeLayers.length; li++) {
    const layer = activeLayers[li]!;
    const nodes = byLayer.get(layer) ?? [];
    const x = colX(li);
    for (let ni = 0; ni < nodes.length; ni++) {
      const node = nodes[ni]!;
      const y = V_PAD + HEADER_H + ni * (NODE_H + NODE_GAP);
      nodePos.set(node.filePath, { x, y: y + NODE_H / 2 });
    }
  }

  const maxNodes = Math.max(...activeLayers.map(l => (byLayer.get(l)?.length ?? 0)));
  const totalH = V_PAD + HEADER_H + maxNodes * (NODE_H + NODE_GAP) + V_PAD;
  const totalW = H_PAD + activeLayers.length * (COL_W + COL_GAP) - COL_GAP + H_PAD;

  const scanPaths  = new Set(scans.map(s => s.filePath));
  const crossEdges = edges.filter(e =>
    scanPaths.has(e.from) && scanPaths.has(e.to) &&
    classifyLayer(e.from) !== classifyLayer(e.to)
  );

  const layerIdx = new Map(LAYER_ORDER.map((l, i) => [l, i]));

  const layerStats = (layer: Layer) => {
    const nodes = byLayer.get(layer) ?? [];
    if (!nodes.length) return null;
    const avg  = nodes.reduce((s, n) => s + n.globalScore, 0) / nodes.length;
    const crit = nodes.filter(n => n.globalScore >= 50).length;
    return { avg, crit, count: nodes.length };
  };

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px 20px' }}>
      {/* Layer legend */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 18, flexWrap: 'wrap' }}>
        {activeLayers.map(l => {
          const stats = layerStats(l);
          if (!stats) return null;
          return (
            <div key={l} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: LAYER_COLORS[l], display: 'inline-block' }} />
                <span style={{ color: LAYER_COLORS[l], fontSize: 10, letterSpacing: '0.12em', fontWeight: 700 }}>{LAYER_LABELS[l]}</span>
              </span>
              <span style={{ fontSize: 9, color: '#4a4a52', paddingLeft: 13 }}>
                {stats.count} files · avg {stats.avg.toFixed(0)}
                {stats.crit > 0 && <span style={{ color: '#ef4444' }}> · {stats.crit} crit</span>}
              </span>
            </div>
          );
        })}
        <div style={{ marginLeft: 'auto', fontSize: 9, color: '#2e2e34', alignSelf: 'center' }}>{crossEdges.length} cross-layer edges</div>
      </div>

      <svg viewBox={`0 0 ${totalW} ${totalH}`} width="100%" style={{ overflow: 'visible', minWidth: totalW }}>
        {/* Lane backgrounds */}
        {activeLayers.map((layer, li) => (
          <rect key={layer} x={colX(li) - 4} y={V_PAD - 10} width={COL_W + 8} height={totalH - V_PAD / 2 - V_PAD + 10} rx={4} fill={LAYER_COLORS[layer]} opacity={0.03} />
        ))}

        {/* Cross-layer edges */}
        {crossEdges.map((e, i) => {
          const from = nodePos.get(e.from);
          const to   = nodePos.get(e.to);
          if (!from || !to) return null;
          const fi      = layerIdx.get(classifyLayer(e.from)) ?? 0;
          const ti      = layerIdx.get(classifyLayer(e.to))   ?? 0;
          const forward = fi < ti;
          const sx = forward ? from.x + COL_W : from.x;
          const ex = forward ? to.x            : to.x + COL_W;
          const mx = (sx + ex) / 2;
          const fromScan = scans.find(s => s.filePath === e.from);
          const edgeColor = fromScan ? scoreColor(fromScan.globalScore) : '#2a2a30';
          return (
            <path key={i} d={`M ${sx} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${ex} ${to.y}`}
              fill="none" stroke={edgeColor} strokeWidth={1} opacity={0.2}
              strokeDasharray={forward ? 'none' : '3,3'}
            />
          );
        })}

        {/* Column headers */}
        {activeLayers.map((layer, li) => {
          const x = colX(li);
          const stats = layerStats(layer);
          return (
            <g key={layer}>
              <rect x={x} y={V_PAD - HEADER_H} width={COL_W} height={HEADER_H - 6} rx={3} fill={LAYER_COLORS[layer]} opacity={0.12} />
              <text x={x + COL_W / 2} y={V_PAD - HEADER_H + 11} textAnchor="middle" fontSize={9} fill={LAYER_COLORS[layer]} fontWeight="700" letterSpacing="0.14em" style={{ fontFamily: 'monospace' }}>
                {LAYER_LABELS[layer]}
              </text>
              {stats && (
                <text x={x + COL_W / 2} y={V_PAD - HEADER_H + 21} textAnchor="middle" fontSize={8} fill={LAYER_COLORS[layer]} opacity={0.5} style={{ fontFamily: 'monospace' }}>
                  {stats.count} file{stats.count > 1 ? 's' : ''}
                </text>
              )}
            </g>
          );
        })}

        {/* Nodes */}
        {activeLayers.map((layer) => {
          const nodes = byLayer.get(layer) ?? [];
          return nodes.map((s, ni) => {
            const li         = activeLayers.indexOf(layer);
            const nx         = colX(li);
            const ny         = V_PAD + HEADER_H + ni * (NODE_H + NODE_GAP);
            const col        = scoreColor(s.globalScore);
            const isSelected = selectedPath === s.filePath;
            const fileName   = s.filePath.split('/').pop() ?? '';
            const inEdges    = crossEdges.filter(e => e.to   === s.filePath).length;
            const outEdges   = crossEdges.filter(e => e.from === s.filePath).length;
            return (
              <g key={s.filePath} style={{ cursor: 'pointer' }} onClick={() => onSelect(isSelected ? null : s)}>
                <rect x={nx} y={ny} width={COL_W} height={NODE_H} rx={3} fill={isSelected ? '#181820' : '#0d0d10'} stroke={isSelected ? col : '#1e1e24'} strokeWidth={isSelected ? 1.5 : 1} />
                <rect x={nx} y={ny} width={2.5} height={NODE_H} rx={1.5} fill={col} opacity={isSelected ? 1 : 0.6} />
                <text x={nx + 9} y={ny + 12} fontSize={9.5} fill={isSelected ? '#e8e8ea' : '#a0a0a8'} style={{ fontFamily: 'monospace', pointerEvents: 'none', userSelect: 'none' }}>
                  {fileName.length > 17 ? fileName.slice(0, 15) + '…' : fileName}
                </text>
                <text x={nx + 9} y={ny + 23} fontSize={8} fill={col} opacity={0.8} style={{ fontFamily: 'monospace', pointerEvents: 'none' }}>
                  {s.globalScore.toFixed(0)}
                </text>
                {(inEdges > 0 || outEdges > 0) && (
                  <text x={nx + COL_W - 6} y={ny + 12} fontSize={8} fill="#3a3a44" textAnchor="end" style={{ fontFamily: 'monospace', pointerEvents: 'none' }}>
                    {inEdges > 0 ? `↙${inEdges}` : ''}{outEdges > 0 ? ` ↗${outEdges}` : ''}
                  </text>
                )}
                <text x={nx + COL_W - 6} y={ny + 23} fontSize={9} fill={s.trend === '↑' ? '#ef4444' : s.trend === '↓' ? '#22c55e' : '#2e2e34'} textAnchor="end" style={{ fontFamily: 'monospace', pointerEvents: 'none' }}>
                  {s.trend}
                </text>
              </g>
            );
          });
        })}
      </svg>
    </div>
  );
}
