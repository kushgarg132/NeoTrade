import React from 'react';

const STYLE = {
  A: { background: 'var(--accent)', color: 'var(--accent-ink)' },
  B: { background: 'var(--surface-2)', color: 'var(--text)' },
  C: { background: 'var(--border)', color: 'var(--text-muted)' },
};

const GradeTile = ({ grade }) => (
  <span aria-label={`Grade ${grade}`} style={STYLE[grade] || STYLE.C}
        className="inline-flex w-9 h-9 items-center justify-center rounded-[12px] text-[17px] font-bold">{grade}</span>
);

export default GradeTile;
