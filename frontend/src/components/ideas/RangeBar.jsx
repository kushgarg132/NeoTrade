import React from 'react';
import { rangeBar } from '../../utils/ideas';
import { pct } from '../ui/format';

/** p10 to p90 bar with the median tick; the faint line is zero. */
const RangeBar = ({ range }) => {
  const r = rangeBar(range.p10, range.median, range.p90);
  return (
    <div>
      <div
        role="img"
        aria-label={`Likely range ${pct(range.p10, { sign: true })} to ${pct(range.p90, { sign: true })}, median ${pct(range.median, { sign: true })}`}
        className="relative h-3 rounded-full bg-[var(--surface-2)]"
      >
        <div className="absolute inset-y-0 w-px bg-[var(--text-muted)]" style={{ left: `${r.zero}%` }} />
        <div className="absolute inset-y-0 rounded-full bg-[var(--accent)] opacity-40" style={{ left: `${r.p10}%`, width: `${r.p90 - r.p10}%` }} />
        <div className="absolute -inset-y-1 w-1 rounded-full bg-[var(--accent)]" style={{ left: `calc(${r.median}% - 2px)` }} />
      </div>
      <div className="mt-2 flex justify-between text-[13px] tabular-nums text-[var(--text-muted)]">
        <span>{pct(range.p10, { sign: true, dp: 1 })} low</span>
        <span className="text-[var(--text)] font-semibold">{pct(range.median, { sign: true, dp: 1 })} median</span>
        <span>{pct(range.p90, { sign: true, dp: 1 })} high</span>
      </div>
    </div>
  );
};

export default RangeBar;
