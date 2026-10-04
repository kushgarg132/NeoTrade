import React from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '../../utils/cn';

/** The go-live rule, said once above a strategy list instead of per row. */
export const GO_LIVE_RULE =
  'To go live a strategy needs a passing year’s backtest, 20 paper days, 30 trades, a net profit after charges, profit factor 1.3 and no fall deeper than 5% of your account.';

/**
 * One strategy on one line: name, a few-word status and an optional control.
 * Tapping the name opens the full text (and anything passed as `extra`) in
 * place; the parent keeps one row open at a time.
 */
const StrategyRow = ({ name, status, detail, extra, open, onToggle, children }) => (
  <div className="border-b border-[var(--rule)] last:border-b-0">
    <div className="flex items-center gap-3 py-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="min-w-0 flex-1 text-left flex items-center gap-2"
      >
        <span className="min-w-0 flex-1">
          <span className="field-label block truncate">{name}</span>
          <span className="doc-meta normal-case block truncate">{status}</span>
        </span>
        <ChevronDown
          className={cn('w-4 h-4 shrink-0 text-[var(--ink-faint)] transition-transform', open && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      {children && <div className="shrink-0">{children}</div>}
    </div>
    {open && (
      <div className="pb-2 doc-meta normal-case">
        {detail}
        {extra}
      </div>
    )}
  </div>
);

export default StrategyRow;
