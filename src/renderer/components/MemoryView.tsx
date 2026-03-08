import { useState } from 'react';
import type { MemoryNote, MemoryType } from '../types';
import SectionLabel from './shared/SectionLabel';

interface Props {
  notes:     MemoryNote[];
  onDismiss: (id: number) => void;
  onSelect?: (subject: string) => void; // pour naviguer vers un fichier
}

const TYPE_ICON: Record<MemoryType, string> = {
  insight: '◆',
  pattern: '⟳',
  fix:     '✓',
  warning: '⚠',
};

const TYPE_COLOR: Record<MemoryType, string> = {
  insight: '#4a9eff',
  pattern: '#f97316',
  fix:     '#22c55e',
  warning: '#ef4444',
};

const TYPE_DESC: Record<MemoryType, string> = {
  insight: 'Structural insight extracted from LLM analysis',
  pattern: 'Developer behavior pattern observed over time',
  fix:     'Solution applied to a resolved terminal error',
  warning: 'Risk confirmed by LLM — requires attention',
};

const ALL_TYPES: MemoryType[] = ['insight', 'warning', 'fix', 'pattern'];

export default function MemoryView({ notes, onDismiss, onSelect }: Props) {
  const [filter, setFilter] = useState<MemoryType | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);

  const visible = filter ? notes.filter(n => n.type === filter) : notes;
  const sorted  = [...visible].sort((a, b) => b.weight - a.weight);

  const counts = ALL_TYPES.reduce<Record<string, number>>((acc, t) => {
    acc[t] = notes.filter(n => n.type === t).length;
    return acc;
  }, {});

  function timeAgo(iso: string): string {
    const ms = Date.now() - new Date(iso).getTime();
    const d  = Math.floor(ms / 86400000);
    const h  = Math.floor(ms / 3600000);
    const m  = Math.floor(ms / 60000);
    if (d > 0)  return `${d}d ago`;
    if (h > 0)  return `${h}h ago`;
    if (m > 0)  return `${m}m ago`;
    return 'just now';
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', fontFamily: 'monospace' }}>

      {/* Header */}
      <div style={{ padding: '22px 40px 16px', borderBottom: '1px solid #1e1e22', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
          <SectionLabel>MEMORY</SectionLabel>
          <span style={{ fontSize: 10, color: '#3a3a44' }}>{notes.length} note{notes.length !== 1 ? 's' : ''}</span>
        </div>

        {/* Filtres par type */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            onClick={() => setFilter(null)}
            style={{
              fontSize: 9, letterSpacing: '0.1em', padding: '3px 8px', borderRadius: 2,
              cursor: 'pointer', fontFamily: 'monospace', border: '1px solid',
              borderColor: filter === null ? '#4a9eff' : '#1e1e22',
              color:       filter === null ? '#4a9eff' : '#3a3a44',
              background:  'transparent', transition: 'all 0.15s',
            }}
          >ALL · {notes.length}</button>

          {ALL_TYPES.filter(t => counts[t]! > 0).map(t => (
            <button
              key={t}
              onClick={() => setFilter(f => f === t ? null : t)}
              style={{
                fontSize: 9, letterSpacing: '0.1em', padding: '3px 8px', borderRadius: 2,
                cursor: 'pointer', fontFamily: 'monospace', border: '1px solid',
                borderColor: filter === t ? TYPE_COLOR[t] : '#1e1e22',
                color:       filter === t ? TYPE_COLOR[t] : '#3a3a44',
                background:  'transparent', transition: 'all 0.15s',
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              <span>{TYPE_ICON[t]}</span>
              <span>{t.toUpperCase()} · {counts[t]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Liste */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 40px 24px' }}>
        {sorted.length === 0 ? (
          <div style={{ color: '#3a3a44', fontSize: 11, marginTop: 24, lineHeight: 1.8 }}>
            {filter
              ? `No ${filter} notes.`
              : 'No memory notes yet.\nNotes are generated automatically after a few scans, feedbacks, and terminal interactions.'
            }
          </div>
        ) : sorted.map(note => {
          const color   = TYPE_COLOR[note.type];
          const icon    = TYPE_ICON[note.type];
          const isHover = hoveredId === note.id;
          const subject = note.subject.split('/').pop() ?? note.subject;
          const isFile  = note.subject.startsWith('/');
          const weightPct = Math.round(note.weight * 100);

          return (
            <div
              key={note.id}
              onMouseEnter={() => setHoveredId(note.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                padding: '14px 0',
                borderBottom: '1px solid #0e0e10',
                display: 'flex',
                gap: 16,
                alignItems: 'flex-start',
              }}
            >
              {/* Icône type */}
              <span style={{ color, fontSize: 14, flexShrink: 0, marginTop: 1, lineHeight: 1, width: 16, textAlign: 'center' }}>{icon}</span>

              {/* Contenu */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  {/* Subject — cliquable si c'est un fichier */}
                  <span
                    onClick={() => isFile && onSelect?.(note.subject)}
                    style={{
                      fontSize: 11, color: isFile ? '#8a8a94' : '#6a6a72',
                      cursor: isFile ? 'pointer' : 'default',
                      borderBottom: isFile ? '1px solid #2a2a32' : '1px solid transparent',
                      transition: 'color 0.15s',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260,
                    }}
                    onMouseEnter={e => { if (isFile) e.currentTarget.style.color = '#d0d0d8'; }}
                    onMouseLeave={e => { if (isFile) e.currentTarget.style.color = '#8a8a94'; }}
                    title={note.subject}
                  >{subject}</span>

                  {/* Badge type */}
                  <span style={{ fontSize: 8, color, letterSpacing: '0.1em', border: `1px solid ${color}33`, borderRadius: 2, padding: '1px 5px', flexShrink: 0 }}>
                    {note.type.toUpperCase()}
                  </span>

                  {/* Timestamp */}
                  <span style={{ marginLeft: 'auto', fontSize: 9, color: '#2a2a32', flexShrink: 0 }}>
                    {timeAgo(note.updatedAt)}
                  </span>
                </div>

                {/* Description type — une ligne, très discrète */}
                <div style={{ fontSize: 9, color: '#2a2a32', marginBottom: 5, lineHeight: 1.4 }}>
                  {TYPE_DESC[note.type]}
                </div>

                {/* Contenu de la note */}
                <div style={{ fontSize: 11, color: '#5a5a62', lineHeight: 1.6, marginBottom: 6 }}>
                  {note.content}
                </div>

                {/* Poids + liens */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6 }}>
                  {/* Barre de poids */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <div style={{ width: 48, height: 2, background: '#1a1a1e', borderRadius: 1, overflow: 'hidden' }}>
                      <div style={{ width: `${weightPct}%`, height: '100%', background: color, opacity: 0.5, borderRadius: 1 }} />
                    </div>
                    <span style={{ fontSize: 8, color: '#2a2a32' }}>{weightPct}%</span>
                  </div>

                  {note.links.length > 0 && (
                    <span style={{ fontSize: 9, color: '#2a2a32' }}>
                      → {note.links.length} linked insight{note.links.length > 1 ? 's' : ''}
                    </span>
                  )}

                  {/* Dismiss */}
                  {isHover && (
                    <button
                      onClick={() => onDismiss(note.id)}
                      style={{ marginLeft: 'auto', fontSize: 9, color: '#2a2a32', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0, transition: 'color 0.15s' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                      onMouseLeave={e => e.currentTarget.style.color = '#2a2a32'}
                    >dismiss</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
