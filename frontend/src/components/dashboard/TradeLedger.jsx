import React, { useState } from 'react';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, Scrip } from '../doc/Doc';
import { Badge as Mark } from '../common/Badge';
import { formatCurrency, formatQuantity, formatClock, formatNoteDate } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * Open and closed round trips. A fill is an execution; a trade is the whole
 * position from the fill that opened it to the one that flattened it, which
 * is the thing a person actually wants to see listed.
 *
 * On a phone the table becomes stacked records rather than a horizontally
 * scrolling grid — a statement column you have to swipe to reach is a column
 * nobody reads.
 */

const TABS = [
  { id: 'OPEN', label: 'Active' },
  { id: 'CLOSED', label: 'Completed' },
];

const ModeMark = ({ mode }) => (
  <Mark variant={mode === 'INTRADAY' ? 'warning' : 'secondary'}>
    {mode === 'INTRADAY' ? 'MIS' : 'CNC'}
  </Mark>
);

const OpenRecord = ({ trade }) => (
  <li className="py-3 border-b border-[var(--rule)] last:border-b-0">
    <div className="flex items-baseline justify-between gap-3">
      <Scrip symbol={trade.symbol} className="text-sm" />
      <Money value={trade.realized_pnl} />
    </div>
    <div className="mt-1.5 flex items-center justify-between gap-3 doc-meta normal-case">
      <span>
        {trade.side} {formatQuantity(trade.quantity)} @ {formatCurrency(trade.entry_price)}
      </span>
      <ModeMark mode={trade.mode} />
    </div>
  </li>
);

const TradeLedger = ({ trades, loading, error }) => {
  const [tab, setTab] = useState('OPEN');
  const rows = (trades || []).filter((trade) => trade.status === tab);

  return (
    <Sheet
      title="Trades"
      actions={
        <div className="flex border border-[var(--rule-strong)]" role="tablist" aria-label="Trade status">
          {TABS.map((item) => {
            const count = (trades || []).filter((t) => t.status === item.id).length;
            const selected = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setTab(item.id)}
                className={cn(
                  'px-2.5 py-1 font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
                  selected
                    ? 'bg-[var(--ink)] text-[var(--paper)]'
                    : 'text-[var(--ink-soft)] hover:text-[var(--ink)]'
                )}
              >
                {item.label}
                <span className={cn('ml-1.5', selected ? 'opacity-70' : 'text-[var(--ink-faint)]')}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      }
    >
      {loading ? (
        <Ruling rows={4} />
      ) : error ? (
        <Empty title="Could not load trades" detail={error} />
      ) : rows.length === 0 ? (
        <Empty
          title={tab === 'OPEN' ? 'No open positions' : 'Nothing closed yet'}
          detail={
            tab === 'OPEN'
              ? 'Approved suggestions and intraday signals will appear here as they fill.'
              : 'Round trips show here once a position returns to flat.'
          }
        />
      ) : (
        <>
          {/* Phone: stacked records. */}
          <ul className="sm:hidden">
            {rows.map((trade) =>
              tab === 'OPEN' ? (
                <OpenRecord key={trade.id} trade={trade} />
              ) : (
                <li key={trade.id} className="py-3 border-b border-[var(--rule)] last:border-b-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <Scrip symbol={trade.symbol} className="text-sm" />
                    <Money value={trade.realized_pnl} />
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-3 doc-meta normal-case">
                    <span>
                      {formatCurrency(trade.entry_price)} → {formatCurrency(trade.exit_price)}
                    </span>
                    <span>{formatNoteDate(new Date(trade.exit_at))}</span>
                  </div>
                </li>
              )
            )}
          </ul>

          {/* Desktop: the ruled table. */}
          <div className="hidden sm:block">
            <Statement
              columns={
                tab === 'OPEN'
                  ? [
                      { key: 'scrip', label: 'Scrip' },
                      { key: 'side', label: 'Side' },
                      { key: 'qty', label: 'Qty', align: 'right' },
                      { key: 'entry', label: 'Entry', align: 'right' },
                      { key: 'since', label: 'Since', align: 'right' },
                      { key: 'pnl', label: 'Realised', align: 'right' },
                    ]
                  : [
                      { key: 'scrip', label: 'Scrip' },
                      { key: 'qty', label: 'Qty', align: 'right' },
                      { key: 'entry', label: 'Entry', align: 'right' },
                      { key: 'exit', label: 'Exit', align: 'right' },
                      { key: 'closed', label: 'Closed', align: 'right' },
                      { key: 'pnl', label: 'P&L', align: 'right' },
                    ]
              }
            >
              {rows.map((trade) => (
                <Row key={trade.id}>
                  <Cell>
                    <Scrip symbol={trade.symbol} />{' '}
                    <ModeMark mode={trade.mode} />
                  </Cell>
                  {tab === 'OPEN' && <Cell>{trade.side}</Cell>}
                  <Cell align="right" mono>
                    {formatQuantity(trade.quantity)}
                  </Cell>
                  <Cell align="right" mono>
                    {formatCurrency(trade.entry_price)}
                  </Cell>
                  {tab === 'CLOSED' && (
                    <Cell align="right" mono>
                      {formatCurrency(trade.exit_price)}
                    </Cell>
                  )}
                  <Cell align="right" className="doc-meta normal-case">
                    {tab === 'OPEN'
                      ? formatClock(trade.entry_at)
                      : formatNoteDate(new Date(trade.exit_at))}
                  </Cell>
                  <Cell align="right">
                    <Money value={trade.realized_pnl} />
                  </Cell>
                </Row>
              ))}
            </Statement>
          </div>
        </>
      )}
    </Sheet>
  );
};

export default TradeLedger;
