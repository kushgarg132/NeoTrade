import React from 'react';
import { formatPercent } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/** Weight change as "12.0% → 18.0%", the after figure green when it grew, red when it shrank. */
const Change = ({ now, after }) => {
  const d = after - now;
  return (
    <span className="figure-md text-sm whitespace-nowrap">
      <span className="doc-meta">{formatPercent(now)} → </span>
      <span className={cn(d > 0.05 && 'text-up', d < -0.05 && 'text-down')}>{formatPercent(after)}</span>
    </span>
  );
};

/** Two thin bars on one track: today's weight (muted) and after the plan (accent). */
const Bars = ({ now, after, max }) => (
  <div className="relative h-3 w-full bg-[var(--surface-2)] rounded-full overflow-hidden" aria-hidden="true">
    <div className="absolute inset-y-0 left-0 top-0 h-1.5 bg-[var(--text-muted)] opacity-50 rounded-full" style={{ width: `${(now / max) * 100}%` }} />
    <div className="absolute left-0 bottom-0 h-1.5 bg-[var(--accent)] rounded-full transition-[width] duration-500" style={{ width: `${(after / max) * 100}%` }} />
  </div>
);

const tag = (r) => (r.value_now <= 0 ? ['New', 'text-up'] : r.value_after <= 0 ? ['Exit', 'text-down'] : null);

/** The book once every trade fills (`plan_rebalance` → `after`): sector mix, then every name. */
const RebalanceAfter = ({ after }) => {
  if (!after?.rows?.length) return null;
  const max = Math.max(1, ...after.sectors.flatMap((s) => [s.weight_now, s.weight_after]));
  return (
    <div className="space-y-4">
      <div>
        <p className="field-label mb-2">Sector mix <span className="doc-meta normal-case">· grey today, colour after</span></p>
        <ul className="space-y-2">
          {after.sectors.map((s) => (
            <li key={s.sector}>
              <div className="flex items-baseline justify-between gap-3 mb-1">
                <span className="text-sm truncate">{s.sector}</span>
                <Change now={s.weight_now} after={s.weight_after} />
              </div>
              <Bars now={s.weight_now} after={s.weight_after} max={max} />
            </li>
          ))}
          {after.cash_pct > 0.05 && (
            <li className="flex items-baseline justify-between gap-3 text-sm">
              <span>Cash left</span><span className="figure-md">{formatPercent(after.cash_pct)}</span>
            </li>
          )}
        </ul>
      </div>
      <div>
        <p className="field-label mb-1">Holdings after</p>
        <ul className="divide-y divide-[var(--border)]">
          {after.rows.map((r) => {
            const t = tag(r);
            return (
              <li key={r.symbol} className="py-2 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="figure-md text-sm">{r.symbol}</span>
                    <span className="rounded-full px-1.5 text-[11px] font-semibold bg-[var(--surface-2)] text-[var(--text-muted)]">{r.kind === 'STOCK' ? 'Stock' : r.kind}</span>
                    {t && <span className={cn('text-[11px] font-semibold', t[1])}>{t[0]}</span>}
                  </div>
                  <div className="doc-meta normal-case truncate">{r.sector}</div>
                </div>
                <Change now={r.weight_now} after={r.weight_after} />
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
};

export default RebalanceAfter;
