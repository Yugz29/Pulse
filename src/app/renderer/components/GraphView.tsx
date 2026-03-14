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
  const [size, setSize]           = useState({ w: 0, h: 0 });
  const nodesRef                  = useRef<SimNode[]>([]);
  const [, forceRender]           = useState(0);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [animating, setAnimating] = useState(false);
  const animTimerRef              = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPanning                 = useRef(false);
  const lastMouse                 = useRef({ x: 0, y: 0 });
  const [tooltip, setTooltip]     = useState<{ x: number; y: number; scan: Scan } | null>(null);
  const simRef                    = useRef<any>(null);
  const sizeRef                   = useRef(size);
  useEffect(() => { sizeRef.current = size; }, [size]);

  // ── ResizeObserver ─────────────────────────────────────────────────────────
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

  // ── fitNodes : optionnellement animé ──────────────────────────────────────
  const fitNodes = useCallback((
    nodeIds: Set<string>,
    padding  = 60,
    animated = true,
    maxZoom  = 1.2,   // zoom max pour fit global
    minSize  = 200,   // plancher en px pour éviter zoom extrême sur 1 nœud isolé
  ) => {
    const nodes = nodesRef.current;
    const { w, h } = sizeRef.current;
    if (!w || !h) return;
    const group = nodes.filter(n => nodeIds.has(n.id) && n.x !== undefined && n.y !== undefined);
    if (!group.length) return;
    const minX = Math.min(...group.map(n => n.x!));
    const maxX = Math.max(...group.map(n => n.x!));
    const minY = Math.min(...group.map(n => n.y!));
    const maxY = Math.max(...group.map(n => n.y!));
    const gw = Math.max(maxX - minX, minSize);
    const gh = Math.max(maxY - minY, minSize);
    const k  = Math.min(maxZoom, Math.max(0.15, Math.min((w - padding * 2) / gw, (h - padding * 2) / gh)));
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    if (animated) {
      setAnimating(true);
      if (animTimerRef.current) clearTimeout(animTimerRef.current);
      animTimerRef.current = setTimeout(() => setAnimating(false), 460);
    }
    setTransform({ x: w / 2 - k * cx, y: h / 2 - k * cy, k });
  }, []);

  // ── panToNode : centre un nœud sans toucher au zoom ────────────────────────
  // Utilisé à la sélection — les autres nœuds restent visibles dans le champ
  const panToNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find(n => n.id === nodeId);
    if (!node || node.x === undefined || node.y === undefined) return;
    const { w, h } = sizeRef.current;
    setAnimating(true);
    if (animTimerRef.current) clearTimeout(animTimerRef.current);
    animTimerRef.current = setTimeout(() => setAnimating(false), 460);
    setTransform(t => ({
      x: w / 2 - t.k * node.x!,
      y: h / 2 - t.k * node.y!,
      k: t.k,                    // zoom inchangé
    }));
  }, []);

  // ── Simulation D3 ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!scans.length || !size.w || !size.h) return;
    const { w, h } = size;
    if (simRef.current) simRef.current.stop();

    // Conserver les positions des nœuds existants pour éviter le respawn aléatoire
    const prevPos = new Map(nodesRef.current.map(n => [n.id, { x: n.x, y: n.y }]));

    const nodes: SimNode[] = scans.map(s => {
      const prev = prevPos.get(s.filePath);
      return {
        id: s.filePath, score: s.globalScore, fanIn: s.fanIn,
        x: prev?.x ?? w / 2 + (Math.random() - 0.5) * 120,
        y: prev?.y ?? h / 2 + (Math.random() - 0.5) * 120,
      };
    });
    nodesRef.current = nodes;

    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const links = edges
      .filter(e => nodeById.has(e.from) && nodeById.has(e.to))
      .map(e => ({ source: e.from, target: e.to }));

    const connectedIds = new Set<string>();
    for (const e of links) {
      connectedIds.add(e.source as string);
      connectedIds.add(e.target as string);
    }

    const sim = forceSimulation(nodes as any[])
      .force('link', (forceLink as any)(links).id((d: any) => d.id).distance(80).strength(0.35))
      .force('charge', forceManyBody().strength((d: any) => connectedIds.has(d.id) ? -200 : -40))
      .force('center', forceCenter(w / 2, h / 2).strength(0.12))
      .force('collide', forceCollide(20).strength(0.9))
      .alphaDecay(0.018);

    let firstTick = true;
    sim.on('tick', () => {
      forceRender(n => n + 1);
      if (firstTick) {
        firstTick = false;
        // Fit immédiat dès le 1er tick, sans animation (positions encore chaotiques)
        // → l'utilisateur voit tous les nœuds dès l'ouverture
        fitNodes(new Set(nodes.map(n => n.id)), 48, false);
      }
    });
    // Fit animé à la fin de la simulation (layout stabilisé)
    sim.on('end', () => fitNodes(new Set(nodes.map(n => n.id)), 48, true));
    simRef.current = sim;
    return () => { sim.stop(); };
  }, [scans, edges, size.w, size.h, fitNodes]);

  // ── Sélection : épingler + pan (zoom inchangé) ────────────────────────────
  useEffect(() => {
    const nodes = nodesRef.current;
    nodes.forEach(n => {
      n.fx = n.id === selectedPath ? (n.x ?? null) : null;
      n.fy = n.id === selectedPath ? (n.y ?? null) : null;
    });

    if (!selectedPath) return;

    // Construire le groupe : nœud sélectionné + voisins directs
    const neighborIds = new Set<string>([selectedPath]);
    for (const e of edges) {
      if (e.from === selectedPath) neighborIds.add(e.to);
      if (e.to   === selectedPath) neighborIds.add(e.from);
    }

    const sim = simRef.current;
    // maxZoom 3.0 : zoom confortable sur le cluster sélectionné
    // minSize 60  : plancher bas → zoome même si les voisins sont proches
    if (!sim || sim.alpha() < 0.01) {
      fitNodes(neighborIds, 80, true, 3.0, 60);
    } else {
      const t = setTimeout(() => fitNodes(neighborIds, 80, true, 3.0, 60), 150);
      return () => clearTimeout(t);
    }
  }, [selectedPath, edges, fitNodes]);

  // ── Zoom centré sur la souris ──────────────────────────────────────────────
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.ctrlKey
      ? e.deltaY * 0.008
      : Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY) * 0.001, 0.08);
    const factor = 1 - delta;
    const rect   = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    setTransform(t => {
      const newK = Math.min(4, Math.max(0.15, t.k * factor));
      const ratio = newK / t.k;
      return {
        x: mouseX - ratio * (mouseX - t.x),
        y: mouseY - ratio * (mouseY - t.y),
        k: newK,
      };
    });
  }, []);

  // ── Pan ────────────────────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as Element).closest('circle, text.node-label')) return;
    setAnimating(false);
    if (animTimerRef.current) clearTimeout(animTimerRef.current);
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

  // ── Render ─────────────────────────────────────────────────────────────────
  const scanMap = new Map(scans.map(s => [s.filePath, s]));
  const nodes   = nodesRef.current;
  type NodePos  = { x: number; y: number };
  const posMap  = new Map<string, NodePos>(nodes.map(n => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]));

  const hasSelection   = selectedPath !== null;
  const connectedEdges = new Set<number>();
  const connectedNodes = new Set<string>();
  if (hasSelection) {
    connectedNodes.add(selectedPath!);
    edges.forEach((e, i) => {
      if (e.from === selectedPath || e.to === selectedPath) {
        connectedEdges.add(i);
        connectedNodes.add(e.from);
        connectedNodes.add(e.to);
      }
    });
  }

  const gStyle: React.CSSProperties = {
    transform:       `translate(${transform.x}px,${transform.y}px) scale(${transform.k})`,
    transformOrigin: '0 0',
    transition:      animating ? 'transform 0.42s cubic-bezier(0.25, 0.46, 0.45, 0.94)' : 'none',
  };

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
        <g style={gStyle}>

          {/* ── Edges ── */}
          {edges.map((e, i) => {
            const from = posMap.get(e.from);
            const to   = posMap.get(e.to);
            if (!from || !to) return null;
            const isConnected = connectedEdges.has(i);
            const dimmed      = hasSelection && !isConnected;
            const edgeColor   = isConnected ? (scoreColor(scanMap.get(e.from)?.globalScore ?? 0)) : '#252528';
            const isOutgoing  = e.from === selectedPath;
            const dx  = to.x - from.x;
            const dy  = to.y - from.y;
            const len = Math.sqrt(dx * dx + dy * dy) || 1;
            const toR = Math.max(5, Math.min(14, 5 + (scanMap.get(e.to)?.fanIn ?? 0) * 0.8)) + 2;
            const ax  = to.x - (dx / len) * toR;
            const ay  = to.y - (dy / len) * toR;
            return (
              <g key={i} opacity={dimmed ? 0.06 : 1} style={{ transition: 'opacity 0.25s' }}>
                <line
                  x1={from.x} y1={from.y} x2={ax} y2={ay}
                  stroke={edgeColor}
                  strokeWidth={isConnected ? 1.5 / transform.k : 1 / transform.k}
                  opacity={isConnected ? 0.9 : 0.5}
                  strokeDasharray={!isOutgoing && isConnected ? `${3 / transform.k},${3 / transform.k}` : undefined}
                />
                {isConnected && (
                  <polygon
                    points={`0,0 ${-5 / transform.k},${-2.5 / transform.k} ${-5 / transform.k},${2.5 / transform.k}`}
                    fill={edgeColor} opacity={0.8}
                    transform={`translate(${ax},${ay}) rotate(${Math.atan2(dy, dx) * 180 / Math.PI})`}
                  />
                )}
              </g>
            );
          })}

          {/* ── Nodes ── */}
          {nodes.map(n => {
            const scan = scanMap.get(n.id);
            if (!scan) return null;
            const pos = posMap.get(n.id);
            if (!pos) return null;
            const r          = Math.max(5, Math.min(14, 5 + n.fanIn * 0.8));
            const col        = scoreColor(n.score);
            const isSelected = selectedPath === n.id;
            const isNeighbor = hasSelection && connectedNodes.has(n.id) && !isSelected;
            const dimmed     = hasSelection && !connectedNodes.has(n.id);
            const fileName   = n.id.split('/').pop() ?? '';
            return (
              <g
                key={n.id}
                transform={`translate(${pos.x},${pos.y})`}
                style={{ cursor: 'pointer', opacity: dimmed ? 0.1 : 1, transition: 'opacity 0.25s' }}
                onClick={() => onSelect(isSelected ? null : scan)}
                onMouseEnter={(e) => {
                  const rect = containerRef.current?.getBoundingClientRect();
                  if (rect) setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, scan });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                {isSelected && <circle r={r + 8} fill={col} opacity={0.15} />}
                {isNeighbor  && <circle r={r + 4} fill={col} opacity={0.08} />}
                <circle
                  r={isSelected ? r + 2 : r}
                  fill={col}
                  opacity={isSelected ? 1 : isNeighbor ? 0.85 : 0.65}
                  stroke={isSelected ? '#e8e8ea' : col}
                  strokeWidth={isSelected ? 1.5 / transform.k : isNeighbor ? 1.5 / transform.k : 0.5 / transform.k}
                  strokeOpacity={isSelected ? 0.9 : isNeighbor ? 0.6 : 0.4}
                />
                {(isSelected || isNeighbor || r > 10) && (
                  <text
                    className="node-label" y={-r - 5} textAnchor="middle"
                    fontSize={8 / transform.k}
                    fill={isSelected ? '#e8e8ea' : isNeighbor ? '#a0a0a8' : '#6a6a72'}
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

      {/* ── Tooltip ── */}
      {tooltip && (
        <div style={{
          position: 'absolute', left: tooltip.x + 12, top: tooltip.y - 10,
          background: '#111113', border: '1px solid #2e2e34', borderRadius: 3,
          padding: '6px 10px', pointerEvents: 'none', zIndex: 50, fontFamily: 'monospace',
        }}>
          <div style={{ fontSize: 11, color: '#d0d0d8', marginBottom: 3 }}>{tooltip.scan.filePath.split('/').pop()}</div>
          <div style={{ fontSize: 10, color: scoreColor(tooltip.scan.globalScore), fontWeight: 600 }}>{tooltip.scan.globalScore.toFixed(1)} tension</div>
          <div style={{ fontSize: 10, color: '#4a4a52', marginTop: 2 }}>fan-in {tooltip.scan.fanIn} · fan-out {tooltip.scan.fanOut}</div>
        </div>
      )}

      {/* ── Légende ── */}
      <div style={{ position: 'absolute', bottom: 14, left: 20, display: 'flex', gap: 16, fontSize: 9, color: '#4a4a52', fontFamily: 'monospace', alignItems: 'center' }}>
        {([['#22c55e', 'stable'], ['#f97316', 'stressed'], ['#ef4444', 'critical']] as const).map(([c, l]) => (
          <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, display: 'inline-block', opacity: 0.8 }} />
            {l}
          </span>
        ))}
        <span style={{ color: '#1e1e22' }}>|</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width={28} height={10} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <line x1={0} y1={5} x2={22} y2={5} stroke="#4a4a52" strokeWidth={1.5} />
            <polygon points="22,5 17,2.5 17,7.5" fill="#4a4a52" />
          </svg>
          imports
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width={28} height={10} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
            <line x1={0} y1={5} x2={22} y2={5} stroke="#4a4a52" strokeWidth={1.5} strokeDasharray="3,2" />
            <polygon points="22,5 17,2.5 17,7.5" fill="#4a4a52" />
          </svg>
          imported by
        </span>
        <span style={{ color: '#2a2a30' }}>· scroll zoom · drag pan</span>
      </div>

      <button
        onClick={() => fitNodes(new Set(nodesRef.current.map(n => n.id)), 48, true)}
        style={{ position: 'absolute', bottom: 14, right: 20, background: 'transparent', border: '1px solid #2e2e34', color: '#4a4a52', fontSize: 9, padding: '3px 8px', borderRadius: 2, cursor: 'pointer', fontFamily: 'monospace' }}
      >
        FIT
      </button>
    </div>
  );
}
