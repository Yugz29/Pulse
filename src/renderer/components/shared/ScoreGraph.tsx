import { scoreColor } from '../../utils';

interface Props {
  history: { score: number; scanned_at: string }[];
}

export default function ScoreGraph({ history }: Props) {
  if (history.length < 2) {
    return <div style={{ color: '#4a4a52', fontSize: 10, marginTop: 4 }}>Not enough data</div>;
  }
  const W = 240, H = 44, pad = 4;
  const scores = history.map(h => h.score);
  const min    = Math.min(...scores);
  const max    = Math.max(...scores) || 1;
  const pts    = scores.map((s, i) => {
    const x = pad + (i / (scores.length - 1)) * (W - pad * 2);
    const y = H - pad - ((s - min) / (max - min || 1)) * (H - pad * 2);
    return `${x},${y}`;
  }).join(' ');
  const lineColor = scoreColor(scores[scores.length - 1] ?? 0);
  return (
    <svg width={W} height={H} style={{ display: 'block', marginTop: 4 }}>
      <polyline points={pts} fill="none" stroke={lineColor} strokeWidth="1" strokeLinejoin="round" opacity="0.7" />
      {scores.map((s, i) => {
        const x = pad + (i / (scores.length - 1)) * (W - pad * 2);
        const y = H - pad - ((s - min) / (max - min || 1)) * (H - pad * 2);
        return <circle key={i} cx={x} cy={y} r={2} fill={lineColor} opacity="0.9" />;
      })}
    </svg>
  );
}
