/**
 * ClipboardHint — pastille discrète pour le mode interrogatif.
 *
 * Différent du TerminalErrorBanner :
 * - Pas d'alerte, pas de couleur rouge
 * - Positionné en bas à droite, non-bloquant
 * - Le contenu clipboard est affiché en preview tronquée
 * - Actions : "explain" (LLM) ou dismiss
 * - Disparaît automatiquement après 30s si ignoré
 */

import { useEffect, useState } from 'react';

interface Props {
  text:      string;
  onExplain: () => void;
  onDismiss: () => void;
  loading:   boolean;
}

export default function ClipboardHint({ text, onExplain, onDismiss, loading }: Props) {
  const [visible, setVisible] = useState(false);

  // Fade-in au montage
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 30);
    return () => clearTimeout(t);
  }, []);

  // Auto-dismiss après 30s si pas d'interaction
  useEffect(() => {
    const t = setTimeout(() => onDismiss(), 30_000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  // Preview : première ligne non-vide, tronquée à 72 chars
  const preview = text
    .split('\n')
    .map(l => l.trim())
    .find(l => l.length > 0)
    ?.slice(0, 72) ?? '';

  const lineCount = text.split('\n').filter(l => l.trim()).length;

  return (
    <div style={{
      position:   'fixed',
      bottom:     20,
      right:      20,
      zIndex:     200,
      fontFamily: 'monospace',
      opacity:    visible ? 1 : 0,
      transform:  visible ? 'translateY(0)' : 'translateY(8px)',
      transition: 'opacity 0.2s ease, transform 0.2s ease',
      maxWidth:   340,
    }}>
      <div style={{
        background:   '#0d0d0f',
        border:       '1px solid #2a2a32',
        borderRadius: 4,
        padding:      '10px 12px',
        boxShadow:    '0 4px 16px rgba(0,0,0,0.5)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 9, color: '#4a9eff', letterSpacing: '0.12em', fontWeight: 700 }}>
            CLIPBOARD
          </span>
          <span style={{ fontSize: 9, color: '#2a2a3a' }}>
            {lineCount > 1 ? `${lineCount} lines` : '1 line'}
          </span>
          <button
            onClick={onDismiss}
            style={{
              marginLeft:  'auto',
              background:  'none',
              border:      'none',
              cursor:      'pointer',
              color:       '#3a3a44',
              fontSize:    14,
              padding:     0,
              lineHeight:  1,
              transition:  'color 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.color = '#6a6a72'}
            onMouseLeave={e => e.currentTarget.style.color = '#3a3a44'}
          >×</button>
        </div>

        {/* Preview */}
        <div style={{
          fontSize:     10,
          color:        '#5a5a64',
          marginBottom: 10,
          overflow:     'hidden',
          textOverflow: 'ellipsis',
          whiteSpace:   'nowrap',
          fontFamily:   'monospace',
        }}>
          {preview}{preview.length >= 72 ? '…' : ''}
        </div>

        {/* Action */}
        <button
          onClick={onExplain}
          disabled={loading}
          style={{
            width:         '100%',
            padding:       '5px 0',
            borderRadius:  2,
            fontSize:      10,
            fontWeight:    700,
            letterSpacing: '0.1em',
            cursor:        loading ? 'default' : 'pointer',
            border:        '1px solid #2a3a4a',
            background:    'transparent',
            color:         loading ? '#3a3a44' : '#4a9eff',
            fontFamily:    'monospace',
            transition:    'all 0.15s',
          }}
          onMouseEnter={e => { if (!loading) e.currentTarget.style.borderColor = '#4a9eff44'; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = '#2a3a4a'; }}
        >
          {loading ? '◌ analyse…' : '▶ EXPLAIN'}
        </button>
      </div>
    </div>
  );
}
