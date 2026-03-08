// ── PULSE UTILS & CONSTANTS ───────────────────────────────────────────────────

import type { Scan, Edge } from './types';

// ── COLORS ────────────────────────────────────────────────────────────────────

export function scoreColor(score: number): string {
  return score >= 50 ? '#ef4444' : score >= 20 ? '#f97316' : '#22c55e';
}

// ── STATUS ────────────────────────────────────────────────────────────────────

export function computeStatus(scans: Scan[]) {
  if (!scans.length) {
    return { label: 'Observing', color: '#4a4a52', tension: 0, complexity: 0, trend: '↔' as const };
  }
  const tension    = scans.reduce((a, s) => a + s.globalScore, 0) / scans.length;
  const complexity = scans.reduce((a, s) => a + s.complexityScore, 0) / scans.length;
  const critCount  = scans.filter(s => s.globalScore >= 50).length;
  const upCount    = scans.filter(s => s.trend === '↑').length;
  const downCount  = scans.filter(s => s.trend === '↓').length;
  const trend      = upCount > downCount ? '↑' as const : downCount > upCount ? '↓' as const : '↔' as const;
  const critRatio  = critCount / scans.length;
  const label      = critRatio > 0.2  || tension >= 50 ? 'Critical'
                   : critRatio >= 0.1 || tension >= 20 ? 'Under Stress'
                   : critCount > 0                     ? 'Mostly Stable'
                   : 'Stable';
  const color      = label === 'Critical'     ? '#ef4444'
                   : label === 'Under Stress' ? '#f97316'
                   : label === 'Mostly Stable' ? '#eab308'
                   : '#22c55e';
  return { label, color, tension, complexity, trend };
}

// ── OBSERVATIONS ──────────────────────────────────────────────────────────────

export function generateObservations(scans: Scan[], edges: Edge[]): string[] {
  if (!scans.length) return ['Awaiting first scan…'];
  const obs: string[] = [];
  obs.push(`${scans.length} modules under analysis`);
  if (edges.length) obs.push(`${edges.length} dependency edges mapped`);
  const crit       = [...scans].filter(s => s.globalScore >= 50).sort((a, b) => b.globalScore - a.globalScore);
  const stressed   = scans.filter(s => s.globalScore >= 20 && s.globalScore < 50);
  const trendingUp = scans.filter(s => s.trend === '↑');
  const highFanIn  = [...scans].filter(s => s.fanIn > 10).sort((a, b) => b.fanIn - a.fanIn);
  const highFanOut = [...scans].filter(s => s.fanOut > 10).sort((a, b) => b.fanOut - a.fanOut);
  if (crit.length)       obs.push(`Critical tension in ${crit[0]!.filePath.split('/').pop()}`);
  if (stressed.length)   obs.push(`${stressed.length} module${stressed.length > 1 ? 's' : ''} under stress`);
  if (trendingUp.length) obs.push(`Complexity increasing in ${trendingUp.length} module${trendingUp.length > 1 ? 's' : ''}`);
  if (highFanIn.length)  obs.push(`${highFanIn[0]!.filePath.split('/').pop()} — high coupling hub (${highFanIn[0]!.fanIn} dependents)`);
  if (highFanOut.length) obs.push(`${highFanOut[0]!.filePath.split('/').pop()} — high dependency spread`);
  if (!crit.length && !stressed.length) {
    obs.push('No anomaly detected');
    obs.push('Architecture within normal parameters');
  }
  return obs;
}

// ── LAYER CLASSIFICATION ──────────────────────────────────────────────────────

export type Layer = 'ui' | 'api' | 'core' | 'db' | 'config';

export function classifyLayer(filePath: string): Layer {
  const p = filePath.toLowerCase();
  if (
    p.includes('/renderer/') || p.includes('/components/') || p.includes('/pages/') ||
    p.includes('/views/') || p.includes('/ui/') ||
    /\/(app|main)\.(tsx|jsx)$/.test(p)
  ) return 'ui';
  if (
    p.includes('/database/') || p.includes('/db/') || p.includes('/models/') ||
    /\/db\.(ts|js)$/.test(p) || p.includes('migration') || p.includes('schema')
  ) return 'db';
  if (
    p.includes('/api/') || p.includes('/routes/') || p.includes('/socket') ||
    p.includes('/handlers/') || p.includes('/controllers/') || p.includes('/endpoints/')
  ) return 'api';
  if (
    p.includes('config') || p.includes('settings') || p.includes('constants') ||
    p.includes('.env') || p.includes('preload')
  ) return 'config';
  return 'core';
}

export const LAYER_LABELS: Record<Layer, string> = {
  ui: 'UI', api: 'API', core: 'CORE', db: 'DATABASE', config: 'CONFIG',
};

export const LAYER_COLORS: Record<Layer, string> = {
  ui: '#4a9eff', api: '#f97316', core: '#a0a0a8', db: '#22c55e', config: '#8b5cf6',
};

export const LAYER_ORDER: Layer[] = ['ui', 'api', 'core', 'db', 'config'];

// ── LLM STYLES (shared across Detail, IntelView, TerminalError) ───────────────

export const LLM_STYLES = `
  .pulse-llm h3 { font-size: 11px; font-weight: 600; margin: 12px 0 4px; color: #e8e8ea; }
  .pulse-llm h2 { font-size: 12px; font-weight: 600; margin: 14px 0 6px; color: #e8e8ea; }
  .pulse-llm p  { margin: 4px 0 8px; line-height: 1.65; color: #8a8a94; }
  .pulse-llm ul, .pulse-llm ol { padding-left: 16px; margin: 4px 0 8px; }
  .pulse-llm li { margin-bottom: 4px; line-height: 1.65; color: #8a8a94; }
  .pulse-llm pre { background: #0d0d0f; border-radius: 2px; padding: 8px 10px; overflow-x: auto; font-size: 10px; margin: 6px 0; border: 1px solid #1e1e22; }
  .pulse-llm code { background: #1a1a1e; border-radius: 2px; padding: 1px 4px; font-size: 10px; font-family: monospace; color: #a0a0a8; }
  .pulse-llm pre code { background: none; padding: 0; color: #7a7a82; }
  .pulse-llm strong { font-weight: 600; color: #d0d0d8; }
  @keyframes pulse-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  @keyframes pulse-dots { 0%, 100% { content: ''; } 33% { content: '.'; } 66% { content: '..'; } }
`;
