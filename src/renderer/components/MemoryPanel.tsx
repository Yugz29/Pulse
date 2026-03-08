import { useState } from 'react';
import type { MemoryNote, MemoryType } from '../types';
import SectionLabel from './shared/SectionLabel';

interface Props {
  notes:     MemoryNote[];
  onDismiss: (id: number) => void;
  onEdit:    (id: number, content: string) => void;
}

const TYPE_ICON: Record<MemoryType, string> = {
  pattern:    '⟳',  // comportement répété
  recurring:  '⚡',  // erreur récurrente
  trend:      '↗',  // dégradation
  connection: '⬡',  // hub à risque
  contrast:   '◈',  // bombe silencieuse
};

const TYPE_COLOR: Record<MemoryType, string> = {
  pattern:    '#f97316',
  recurring:  '#ef4444',
  trend:      '#f97316',
  connection: '#eab308',
  contrast:   '#6a8aaa',
};

export default function MemoryPanel({ notes, onDismiss, onEdit }: Props) {
  const [editingId,      setEditingId]      = useState<number | null>(null);
  const [editingContent, setEditingContent] = useState('');
  const [hoveredId,      setHoveredId]      = useState<number | null>(null);

  if (notes.length === 0) return null;

  function startEdit(note: MemoryNote) {
    setEditingId(note.id);
    setEditingContent(note.content);
  }

  function commitEdit(id: number) {
    if (editingContent.trim()) onEdit(id, editingContent.trim());
    setEditingId(null);
  }

  return (
    <div style={{ borderTop: '1px solid #111113', padding: '14px 16px 4px' }}>
      <div style={{ marginBottom: 10 }}><SectionLabel>MEMORY</SectionLabel></div>

      {notes.slice(0, 6).map(note => {
        const color   = TYPE_COLOR[note.type];
        const icon    = TYPE_ICON[note.type];
        const isHover = hoveredId === note.id;
        const isEdit  = editingId  === note.id;

        return (
          <div
            key={note.id}
            onMouseEnter={() => setHoveredId(note.id)}
            onMouseLeave={() => setHoveredId(null)}
            style={{ padding: '6px 0', borderBottom: '1px solid #0e0e10' }}
          >
            {isEdit ? (
              /* Mode édition */
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <textarea
                  value={editingContent}
                  onChange={e => setEditingContent(e.target.value)}
                  autoFocus
                  rows={2}
                  style={{
                    background: '#0d0d0f', border: '1px solid #2e2e34', borderRadius: 2,
                    color: '#d0d0d8', fontSize: 10, fontFamily: 'monospace',
                    padding: '4px 6px', resize: 'none', lineHeight: 1.5, outline: 'none',
                  }}
                />
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => commitEdit(note.id)}
                    style={{ fontSize: 9, color: '#22c55e', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0 }}>
                    save
                  </button>
                  <button onClick={() => setEditingId(null)}
                    style={{ fontSize: 9, color: '#3a3a44', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0 }}>
                    cancel
                  </button>
                </div>
              </div>
            ) : (
              /* Mode lecture */
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7 }}>
                <span style={{ color, fontSize: 10, flexShrink: 0, marginTop: 1, lineHeight: 1 }}>{icon}</span>
                <span style={{ fontSize: 10, color: '#5a5a62', lineHeight: 1.5, flex: 1 }}>
                  {note.content}
                </span>
                {isHover && (
                  <div style={{ display: 'flex', gap: 5, flexShrink: 0, marginTop: 1 }}>
                    <button onClick={() => startEdit(note)}
                      style={{ fontSize: 9, color: '#3a3a44', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0, lineHeight: 1, transition: 'color 0.15s' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#8a8a94'}
                      onMouseLeave={e => e.currentTarget.style.color = '#3a3a44'}
                    >edit</button>
                    <button onClick={() => onDismiss(note.id)}
                      style={{ fontSize: 9, color: '#3a3a44', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', padding: 0, lineHeight: 1, transition: 'color 0.15s' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                      onMouseLeave={e => e.currentTarget.style.color = '#3a3a44'}
                    >×</button>
                  </div>
                )}
              </div>
            )}

            {/* Liens vers d'autres notes */}
            {note.links.length > 0 && !isEdit && (
              <div style={{ fontSize: 9, color: '#2a2a32', marginTop: 3, paddingLeft: 17 }}>
                → {note.links.length} linked insight{note.links.length > 1 ? 's' : ''}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
