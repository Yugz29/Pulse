interface Props {
  label: string;
  score: number;
  desc: string;
  rawLabel?: string;
  rawValue?: number | string;
}

export default function MetricBar({ label, score, desc, rawLabel, rawValue }: Props) {
  const color = score >= 66 ? '#ef4444' : score >= 33 ? '#f97316' : '#22c55e';
  return (
    <div style={{ padding: '9px 0', borderBottom: '1px solid #111113' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: '#8a8a94', letterSpacing: '0.08em', fontWeight: 600 }}>{label}</span>
        <span style={{ fontSize: 12, color, fontWeight: 600 }}>{score.toFixed(1)}</span>
      </div>
      <div style={{ height: 2, background: '#1a1a1e', borderRadius: 1, marginBottom: 5, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(100, score)}%`, background: color, borderRadius: 1, transition: 'width 0.4s ease' }} />
      </div>
      <div style={{ fontSize: 9, color: '#4a4a52', lineHeight: 1.55 }}>
        {desc}
        {rawValue !== undefined && rawLabel && (
          <span style={{ color: '#3a3a42', marginLeft: 5 }}>· {rawLabel}: {rawValue}</span>
        )}
      </div>
    </div>
  );
}
