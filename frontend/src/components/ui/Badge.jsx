import React from 'react';

const KINDS = {
  proven: 'bg-[var(--gain-wash)] text-[var(--gain)]',
  unproven: 'bg-[var(--surface-2)] text-[var(--warn)]',
  paper: 'bg-[var(--accent-soft)] text-[var(--accent)]',
  live: 'bg-[var(--loss-wash)] text-[var(--loss)]',
  alert: 'bg-[var(--loss-wash)] text-[var(--loss)]',
  neutral: 'bg-[var(--surface-2)] text-[var(--text-muted)]',
};

/** A small status pill. */
const Badge = ({ kind = 'neutral', children }) => (
  <span className={`inline-flex items-center rounded-full px-2 min-h-6 text-[12px] font-semibold ${KINDS[kind] || KINDS.neutral}`}>
    {children}
  </span>
);

export default Badge;
