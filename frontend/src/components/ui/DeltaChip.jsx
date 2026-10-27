import React from 'react';
import { inr, pct } from './format';

/** Today's change as a pill: rupees, percent (1.65 = 1.65%), optional suffix. */
const DeltaChip = ({ value, pct: p, suffix, format = inr, privateValue = true }) => {
  const dir = typeof value !== 'number' ? p : value;
  const up = dir > 0;
  const down = dir < 0;
  const bg = up ? '--gain-soft' : down ? '--loss-soft' : '--surface-2';
  const fg = up ? 'text-[var(--gain)]' : down ? 'text-[var(--loss)]' : 'text-[var(--text-muted)]';
  return (
    <span className={`${privateValue ? 'private ' : ''}inline-flex items-center gap-1 rounded-full px-3 py-1 text-[15px] font-semibold tabular-nums ${fg}`} style={{ background: `var(${bg})` }}>
      {up && <span aria-hidden="true">▲</span>}
      {down && <span aria-hidden="true">▼</span>}
      {typeof value === 'number' && format(value, { sign: true })}
      {typeof p === 'number' && (typeof value === 'number' ? ` (${pct(p / 100, { sign: true })})` : pct(p / 100, { sign: true }))}
      {suffix && <span className="font-medium text-[var(--text-muted)]"> {suffix}</span>}
    </span>
  );
};

export default DeltaChip;
