import { useState, useEffect, useCallback, useRef } from 'react';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import type { Scan, Edge } from '../types';
import { scoreColor } from '../utils';

type SimNode = {
  id: string; score: number; fanIn: number;
  x?: number; y?: number; vx?: number; vy?: number; fx?: number | null; fy?: number | null;
};

interface Props {
  scans: Scan[];
  edges: Edge[];
  onSelect: (s: Scan | null) => void;
  selectedPath: string | null;
}

export default function GraphView({ scans, edges, onSelect, selectedPath }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize]      = useState({ w: 600, h: 400 });
  const nodesRef             = useRef<SimNode[]>([]);
  const [, forceRender]      = useState(0);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const isPanning            = useRef(false);
  const lastMouse            = useRef({ x: 0, y: 0 });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; scan: Scan } | null>(null);
  const simRef               = useRef<any>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const e = entries[0];
      if (e) setSize({ w: e.contentRect.width, h: e.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!scans.length || !size.w) return;
    if (simRef.current) simRef.current.stop();

    const nodes: SimNode[] = scans.map(s => ({
      id: s.filePath, score: s.globalScore, fanIn: s.fanIn,
      x: size.w / 2 + (Math.random() - 0.5) * 200,
      y: size.h / 2 + (Math.random() - 0.5) * 200,
    }));
    nodesRef.current = nodes;

    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const links = edges
      .filter(e => nodeById.has(e.from) && nodeById.has(e.to))
      .map(e => ({ source: e.from, target: e.to }));

    const sim = forceSimulation(nodes as any[])
      .force('link', (forceLink as any)(links).id((d: any) => d.id).distance(90).strength(0.25))
      .force('charge', forceManyBody().strength(-180))
      .force('center', forceCenter(size.w / 2, size.h / 2).strength(0.05))
      .force('collide', forceCollide(22).strength(0.8))
      .alphaDecay(0.015);

    sim.on('tick', () => forceRender(n => n + 1));
    simRef.current = sim;
    return () => { sim.stop(); };
  }, [scans, edges, size]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.9;
    setTransform(t => ({ ...t, k: Math.min(4, Math.max(0.15, t.k * factor)) }));
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as Element).closest('circle, text.node-label')) return;
    isPanning.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning.current) return;
    const dx = e.clientX - lastMouse.current.x;
    const dy = e.clientY - lastMouse.current.y;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    setTransform(t => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, []);

  const handleMouseUp = useCallback(() => { isPanning.current = false; }, []);

  const scanMap = new Map(scans.map(s => [s.filePath, s]));
  const nodes   = nodesRef.current;
  type NodePos  = { x: number; y: number };
  const posMap  = new Map<string, NodePos>(nodes.map(n => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]));

  return (
    <div
      ref={containerRef}
      style={{ flex: 1, overflow: 'hidden', position: 'relative', cursor: isPanning.current ? 'grabbing' : 'grab' }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <svg width="100%" height="100%" style={{ display: 'block' }}>
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {edges.map((e, i) => {
            const from = posMap.get(e.from);
            const to   = posMap.get(e.to);
            if (!from || !to) return null;
            return <line key={i} x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#252528" strokeWidth={1 / transform.k} opacity={0.8} />;
          })}
          {nodes.map(n => {
            const scan = scanMap.get(n.id);
            if (!scan) return null;
            const pos = posMap.get(n.id);
            if (!pos) return null;
            const r          = Math.max(5, Math.min(14, 5 + n.fanIn * 0.8));
            const col        = scoreColor(n.score);
            const isSelected = selectedPath === n.id;
            const fileName   = n.id.split('/').pop() ?? '';
            return (
              <g key={n.id} transform={`translate(${pos.x},${pos.y})`} style={{ cursor: 'pointer' }}
                onClick={() => onSelect(isSelected ? null : scan)}
                onMouseEnter={(e) => {
                  const rect = containerRef.current?.getBoundingClientRect();
                  if (rect) setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, scan });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                {isSelected && <circle r={r + 6} fill={col} opacity={0.12} />}
                <circle r={isSelected ? r + 2 : r} fill={col} opacity={isSelected ? 1 : 0.65}
                  stroke={isSelected ? '#e8e8ea' : col}
                  strokeWidth={isSelected ? 1.5 / transform.k : 0.5 / transform.k}
                  strokeOpacity={0.4}
                />
                {(isSelected || r > 10) && (
                  <text className="node-label" y={-r - 5} textAnchor="middle"
                    fontSize={8 / transform.k}
                    fill={isSelected ? '#d0d0d8' : '#6a6a72'}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {fileName.length > 18 ? fileName.slice(0, 16) + '…' : fileName}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {tooltip && (
        <div style={{ position: 'absolute', left: tooltip.x + 12, top: tooltip.y - 10, background: '#111113', border: '1px solid #2e2e34', borderRadius: 3, padding: '6px 10px', pointerEvents: 'none', zIndex: 50, fontFamily: 'monospace' }}>
          <div style={{ fontSize: 11, color: '#d0d0d8', marginBottom: 3 }}>{tooltip.scan.filePath.split('/').pop()}</div>
          <div style={{ fontSize: 10, color: scoreColor(tooltip.scan.globalScore), fontWeight: 600 }}>{tooltip.scan.globalScore.toFixed(1)} tension</div>
          <div style={{ fontSize: 10, color: '#4a4a52', marginTop: 2 }}>fan-in {tooltip.scan.fanIn} · fan-out {tooltip.scan.fanOut}</div>
        </div>
      )}

      <div style={{ position: 'absolute', bottom: 14, left: 20, display: 'flex', gap: 16, fontSize: 9, color: '#4a4a52', fontFamily: 'monospace' }}>
        {([['#22c55e', 'stable'], ['#f97316', 'stressed'], ['#ef4444', 'critical']] as const).map(([c, l]) => (
          <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, display: 'inline-block', opacity: 0.8 }} />
            {l}
          </span>
        ))}
        <span style={{ color: '#2a2a30' }}>· scroll zoom · drag pan</span>
      </div>

      <button onClick={() => setTransform({ x: 0, y: 0, k: 1 })} style={{ position: 'absolute', bottom: 14, right: 20, background: 'transparent', border: '1px solid #2e2e34', color: '#4a4a52', fontSize: 9, padding: '3px 8px', borderRadius: 2, cursor: 'pointer', fontFamily: 'monospace' }}>
        RESET
      </button>
    </div>
  );
}
