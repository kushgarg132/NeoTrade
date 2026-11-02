import React from 'react';

const STYLE = {
  A: { background: 'var(--accent)', color: 'var(--accent-ink)' },
  B: { background: 'var(--surface-2)', color: 'var(--text)' },
  C: { background: 'var(--border)', color: 'var(--text-muted)' },
};

/** The grade letter on its tile; `small` for list rows. */
const GradeTile = ({ grade, small = false }) => (
  <span aria-label={`Grade ${grade}`} style={STYLE[grade] || STYLE.C}
        className={`inline-flex shrink-0 items-center justify-center font-bold ${small ? 'w-6 h-6 rounded-[8px] text-[13px]' : 'w-9 h-9 rounded-[12px] text-[17px]'}`}>{grade}</span>
);

export default GradeTile;
