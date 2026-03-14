import { useState } from 'react';

interface Props {
  onMouseDown: (e: React.MouseEvent) => void;
  onToggle: () => void;
  collapsed: boolean;
  collapseToward: 'left' | 'right';
}

export default function ResizeHandle({ onMouseDown, onToggle, collapsed, collapseToward }: Props) {
  const [hovered, setHovered] = useState(false);
  const arrow = collapseToward === 'left'
    ? (collapsed ? '›' : '‹')
    : (collapsed ? '‹' : '›');

  return (
    <div
      onMouseDown={onMouseDown}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: 4, flexShrink: 0,
        background: hovered ? '#4a9eff22' : 'transparent',
        borderLeft: '1px solid #1e1e22',
        cursor: 'col-resize', position: 'relative',
        transition: 'background 0.15s', zIndex: 10,
      }}
    >
      <div
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 14, height: 28, borderRadius: 3,
          border: '1px solid #2e2e34', background: '#111113',
          color: '#6a6a72', cursor: 'pointer',
          display: hovered ? 'flex' : 'none',
          alignItems: 'center', justifyContent: 'center',
          fontSize: 9, userSelect: 'none', zIndex: 20,
        }}
      >
        {arrow}
      </div>
    </div>
  );
}
