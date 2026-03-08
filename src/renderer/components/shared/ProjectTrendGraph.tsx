import { scoreColor } from '../../utils';

interface Props {
  history: { date: string; score: number }[];
}

export default function ProjectTrendGraph({ history }: Props) {
  if (history.length < 2) return null;
  const W = 120, H = 28, pad = 2;
  const scores = history.map(h => h.score);
  const min    = Math.min(...scores);
  const max    = Math.max(...scores) || 1;
  const pts    = scores.map((s, i) => {
    const x = pad + (i / (scores.length - 1)) * (W - pad * 2);
    const y = H - pad - ((s - min) / (max - min || 1)) * (H - pad * 2);
    return `${x},${y}`;
  }).join(' ');
  const col = scoreColor(scores[scores.length - 1] ?? 0);
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.5" strokeLinejoin="round" opacity="0.7" />
    </svg>
  );
}
