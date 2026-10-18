import React from 'react';
import { Sheet, Money } from '../doc/Doc';
import { formatCurrency } from '../../utils/formatters';

/**
 * Real-money figures as two labelled rows, never summed: orders placed on the
 * user's own account (`mine`) and the AI account's live autopilot (`ai`).
 * `live` is `{mine, ai}` from `GET /analytics/pnl?venue=live` or the `pnl`
 * socket topic. The AI row is hidden until that account has live trades.
 */
const hasTrades = (book) => !!book && (book.all_time?.trades > 0 || book.open?.positions > 0);

const Line = ({ label, book }) => {
  const today = book.today || {};
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <span className="text-[var(--ink-soft)]">
        {label}
        <span className="ml-2 doc-meta normal-case">
          {formatCurrency(book.month?.net || 0)} this month · {book.open?.positions || 0} open
        </span>
      </span>
      <Money value={(today.net ?? today.realized ?? 0) + (today.unrealized || 0)} />
    </div>
  );
};

const LivePnl = ({ live }) => {
  if (!live || !(hasTrades(live.mine) || hasTrades(live.ai))) return null;
  return (
    <Sheet title="Live P&L today" meta="Net of charges">
      {live.mine && <Line label="Your account" book={live.mine} />}
      {hasTrades(live.ai) && <Line label="AI account" book={live.ai} />}
    </Sheet>
  );
};

export default LivePnl;
