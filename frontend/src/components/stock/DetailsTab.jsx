import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Badge from '../ui/Badge';
import ThesisEditor from '../mine/ThesisEditor';
import StockFlags from '../analysis/StockFlags';
import TradingLevels from '../analysis/TradingLevels';
import TechGauge from './TechGauge';
import Fundamentals from '../analysis/Fundamentals';
import { REASONS } from '../../utils/mine';
import { day, verdictLabel, verdictKind } from './common';

/** Verdict (when held), your thesis, then the instant snapshot. The AI read lives in the card above the tabs. */
const DetailsTab = ({ symbol, mine, quick, reloadQuick, onThesis }) => {
  const v = mine?.verdict;
  const company = quick.data?.company_info;
  const currency = company?.currency || 'INR';
  return (
    <div className="space-y-3">
      {v?.current && (
        <Card title="Our verdict">
          <Badge kind={verdictKind(v.current)}>{verdictLabel(v.current)}</Badge>
          {v.reasons?.length > 0 && (
            <ul className="mt-3 space-y-1 text-[14px] text-[var(--text-muted)]">
              {v.reasons.map((c) => <li key={c}>{REASONS[c] || c.replace(/_/g, ' ')}</li>)}
            </ul>
          )}
          {v.note && <p className="mt-3 text-[15px] text-[var(--text)]">{v.note}</p>}
          {v.history?.length > 0 && (
            <ul className="mt-3">
              {[...v.history].reverse().map((h, i) => (
                <li key={i} className="flex justify-between min-h-9 items-center border-t border-[var(--border)] text-[14px]">
                  <span className="text-[var(--text-muted)]">{day(h.date)}</span>
                  <span className="font-semibold text-[var(--text)]">{verdictLabel(h.verdict)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {mine && (
        <Card title="Your thesis">
          <ThesisEditor symbol={symbol} thesis={mine.thesis} onSaved={onThesis} />
        </Card>
      )}

      {quick.loading && <Card><Skeleton rows={4} /></Card>}
      {quick.error && <Card><ErrorLine message={`Could not load the price snapshot${quick.error !== 'Could not load' ? `: ${quick.error}` : ''}. Check your connection and retry.`} onRetry={reloadQuick} /></Card>}
      {quick.data && (
        <>
          <TechGauge t={quick.data.technical_analysis} />
          <StockFlags flags={quick.data.flags} />
          <TradingLevels t={quick.data.technical_analysis} currency={currency} />
          <Fundamentals company={company} currency={currency} />
        </>
      )}
    </div>
  );
};

export default DetailsTab;
