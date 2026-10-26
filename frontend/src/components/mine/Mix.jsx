import React from 'react';
import { Sheet } from '../doc/Doc';
import { formatPercent } from '../../utils/formatters';
import { kindLabel } from '../../utils/money';

const Line = ({ label, children }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5">
    <span className="text-sm text-[var(--text-muted)]">{label}</span>
    <span className="figure-md text-sm tabular-nums text-right">{children}</span>
  </div>
);

/** Sector bars, largest holding, top five, correlated pairs. */
const Mix = ({ concentration, count }) => (
  <Sheet title="How spread out">
    <Line label="Largest holding">
      {concentration.top_symbol} · {formatPercent(concentration.top_pct)}
    </Line>
    <Line label="Top five together">{formatPercent(concentration.top5_pct)}</Line>
    {concentration.effective_holdings && count > 0 && (
      <p className="doc-meta normal-case py-1.5">
        Your {count} holdings are weighted like {concentration.effective_holdings.toFixed(1)} equal ones.
      </p>
    )}
    {concentration.types?.length > 1 && (
      <>
        <p className="field-label mt-3 mb-1">By type</p>
        {concentration.types.map((t) => <Line key={t.kind} label={kindLabel(t.kind)}>{formatPercent(t.pct)}</Line>)}
      </>
    )}
    <p className="field-label mt-3 mb-2">By sector <span className="doc-meta normal-case">· stocks only</span></p>
    <ul className="space-y-1.5">
      {concentration.sectors.map((sector) => (
        <li key={sector.sector}>
          <div className="flex justify-between text-sm">
            <span className="text-[var(--text-muted)]">{sector.sector}</span>
            <span className="figure-md">{formatPercent(sector.pct)}</span>
          </div>
          <div className="h-1.5 bg-[var(--surface-2)] mt-1" aria-hidden="true">
            <div className="h-full bg-[var(--text)]" style={{ width: `${Math.min(sector.pct, 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
    {concentration.correlated.length > 0 && (
      <>
        <p className="field-label mt-4 mb-1">Move together</p>
        <ul>
          {concentration.correlated.map((pair) => (
            <li key={`${pair.a}-${pair.b}`} className="text-sm py-1 text-[var(--text-muted)]">
              {pair.a} and {pair.b} — {pair.correlation.toFixed(2)} correlation over a year, closer to one
              bet than two
            </li>
          ))}
        </ul>
      </>
    )}
  </Sheet>
);

export default Mix;
