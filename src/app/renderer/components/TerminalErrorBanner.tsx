import type { TerminalErrorNotification } from '../types';

interface Props {
  ctx: TerminalErrorNotification;
  onDismiss: () => void;
  onAnalyze: () => void;
  onResolve: () => void;
}

export default function TerminalErrorBanner({ ctx, onDismiss, onAnalyze, onResolve }: Props) {
  const isRecurring = ctx.pastOccurrences > 1;
  const lastSeenStr = ctx.lastSeen
    ? new Date(ctx.lastSeen).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
    : null;

  return (
    <div style={{
      background: '#0f0808', borderBottom: '1px solid #3a1010',
      padding: '7px 20px', display: 'flex', alignItems: 'center',
      gap: 12, flexShrink: 0, fontFamily: 'monospace',
    }}>
      <span style={{ color: '#ef4444', fontSize: 10, letterSpacing: '0.1em', flexShrink: 0, fontWeight: 700 }}>ERR</span>
      <code style={{ fontSize: 11, color: '#a0a0a8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {ctx.command.length > 70 ? ctx.command.slice(0, 70) + '…' : ctx.command}
      </code>
      <span style={{ color: '#4a4a52', fontSize: 10, flexShrink: 0 }}>exit:{ctx.exit_code}</span>
      {isRecurring && (
        <span style={{ color: '#f97316', fontSize: 10, flexShrink: 0 }}>
          ×{ctx.pastOccurrences}{lastSeenStr ? ` · ${lastSeenStr}` : ''}
        </span>
      )}
      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
        <button onClick={onAnalyze} style={{ padding: '3px 9px', borderRadius: 2, fontSize: 10, fontWeight: 700, cursor: 'pointer', border: '1px solid #ef4444', background: 'transparent', color: '#ef4444', fontFamily: 'monospace', letterSpacing: '0.08em' }}>ANALYZE</button>
        <button onClick={onResolve} style={{ padding: '3px 9px', borderRadius: 2, fontSize: 10, cursor: 'pointer', border: '1px solid #22c55e', background: 'transparent', color: '#22c55e', fontFamily: 'monospace', letterSpacing: '0.08em' }}>RESOLVED</button>
        <button onClick={onDismiss} style={{ padding: '3px 9px', borderRadius: 2, fontSize: 10, cursor: 'pointer', border: '1px solid #2e2e34', background: 'transparent', color: '#6a6a72', fontFamily: 'monospace', letterSpacing: '0.08em' }}>DISMISS</button>
      </div>
    </div>
  );
}
