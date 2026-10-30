import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Badge from '../ui/Badge';
import StockFlags from '../analysis/StockFlags';
import TradingLevels from '../analysis/TradingLevels';
import TechGauge from './TechGauge';
import { REASONS } from '../../utils/mine';
import { day, verdictLabel, verdictKind } from './common';
import { toneText } from '../ui/tone';
import { keyNumbers, plainNote, reasonFact } from '../../utils/verdict';

/** Verdict (when held: each rule with its figures, key numbers, the AI note), then the instant snapshot. The AI read lives in the card above the tabs; fundamentals sit under the chart. */
const DetailsTab = ({ mine, quick, reloadQuick }) => {
  const v = mine?.verdict;
  const company = quick.data?.company_info;
  const currency = company?.currency || 'INR';
  const numbers = keyNumbers(v?.facts);
  return (
    <div className="space-y-3">
      {v?.current && (
        <Card title="Our verdict" action={<Badge kind={verdictKind(v.current)}>{verdictLabel(v.current)}</Badge>}>
          {v.since && <p className="-mt-1 text-[13px] text-[var(--text-muted)]">Since {day(v.since)}</p>}
          {v.reasons?.length > 0 && (
            <ul className="mt-3 space-y-2.5">
              {v.reasons.map((c) => {
                const fact = reasonFact(c, v.facts, v.limits);
                return (
                  <li key={c}>
                    <div className="text-[15px] font-medium text-[var(--text)]">{REASONS[c] || c.replace(/_/g, ' ')}</div>
                    {fact && <div className="private text-[13px] tabular-nums text-[var(--text-muted)]">{fact}</div>}
                  </li>
                );
              })}
            </ul>
          )}
          {numbers.length > 0 && (
            <div className="mt-4 pt-3 border-t border-[var(--border)] grid grid-cols-2 gap-x-4 gap-y-3">
              {numbers.map(([label, value, t]) => (
                <div key={label} className="min-w-0">
                  <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
                  <div className={`private text-[15px] font-semibold tabular-nums truncate ${toneText(t)}`}>{value}</div>
                </div>
              ))}
            </div>
          )}
          {v.note && (
            <div className="mt-4 pt-3 border-t border-[var(--border)]">
              <p className="text-[13px] text-[var(--text-muted)] mb-1">AI note</p>
              <p className="text-[14px] text-[var(--text)]">{plainNote(v.note)}</p>
            </div>
          )}
          {v.history?.length > 1 && (
            <p className="mt-3 text-[13px] text-[var(--text-muted)]">
              Earlier: {[...v.history].reverse().slice(1).map((h) => `${verdictLabel(h.verdict)} from ${day(h.date)}`).join(' · ')}
            </p>
          )}
        </Card>
      )}

      {quick.loading && <Card><Skeleton rows={4} /></Card>}
      {quick.error && <Card><ErrorLine message={`Could not load the price snapshot${quick.error !== 'Could not load' ? `: ${quick.error}` : ''}. Check your connection and retry.`} onRetry={reloadQuick} /></Card>}
      {quick.data && (
        <>
          <TechGauge t={quick.data.technical_analysis} />
          <StockFlags flags={quick.data.flags} />
          <TradingLevels t={quick.data.technical_analysis} currency={currency} />
        </>
      )}
    </div>
  );
};

export default DetailsTab;
