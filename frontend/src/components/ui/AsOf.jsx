import React from 'react';
import { asOf } from '../../utils/formatters';

/** The freshness line under market rows: the newest row's `at`, "Stale ·" in warn when old. */
const AsOf = ({ rows, at }) => {
  const newest = at ?? Math.max(0, ...(rows || []).map((r) => (typeof r.at === 'number' ? r.at : 0)));
  const f = asOf(newest || null);
  if (!f) return null;
  return (
    <p className={`mt-2 text-[12px] ${f.stale ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>
      {f.stale ? `Stale · ${f.text}` : f.text}
    </p>
  );
};

export default AsOf;
