import React, { useState } from 'react';
import Card from '../ui/Card';
import Tabs from '../ui/Tabs';
import Badge from '../ui/Badge';
import Empty from '../ui/Empty';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import { inr, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { formatQuantity, formatNoteDate } from '../../utils/formatters';

/**
 * Open and closed round trips. A fill is an execution; a trade is the whole position from the fill
 * that opened it to the one that flattened it, which is the thing a person actually wants to see listed.
 */
const Record = ({ trade, open }) => (
  <li className="py-3 border-b border-[var(--border)] last:border-b-0">
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[15px] font-medium text-[var(--text)]">
        {trade.symbol} <Badge kind="neutral">{trade.mode === 'INTRADAY' ? 'MIS' : 'CNC'}</Badge>
      </span>
      <span className={`private figure-md tabular-nums text-[15px] ${toneText(tone(trade.realized_pnl))}`}>{inr(trade.realized_pnl, { sign: true })}</span>
    </div>
    <div className="mt-1 flex items-center justify-between gap-3 text-[13px] text-[var(--text-muted)] tabular-nums">
      <span className="private">
        {open
          ? `${trade.side} ${formatQuantity(trade.quantity)} @ ${inr(trade.entry_price)}`
          : `${inr(trade.entry_price)} → ${inr(trade.exit_price)}${trade.closed_by === 'inferred_from_holdings' ? ' · inferred from your holdings' : ''}`}
      </span>
      {!open && <span>{formatNoteDate(new Date(trade.exit_at))}</span>}
    </div>
  </li>
);

const TradeLedger = ({ trades, loading, error, title = 'Trades', emptyOpen, emptyClosed }) => {
  const [tab, setTab] = useState('OPEN');
  const count = (status) => (trades || []).filter((t) => t.status === status).length;
  const rows = (trades || []).filter((trade) => trade.status === tab);

  return (
    <Card title={title}>
      <div className="mb-2">
        <Tabs tabs={[{ id: 'OPEN', label: `Active ${count('OPEN')}` }, { id: 'CLOSED', label: `Completed ${count('CLOSED')}` }]} value={tab} onChange={setTab} label="Trade status" />
      </div>
      {loading ? <Skeleton rows={4} /> : error ? <ErrorLine message={`Could not load trades: ${error}`} /> : rows.length === 0 ? (
        <Empty
          title={tab === 'OPEN' ? 'No open positions' : 'Nothing closed yet'}
          body={tab === 'OPEN'
            ? emptyOpen || 'Approved suggestions and intraday signals will appear here as they fill.'
            : emptyClosed || 'Round trips show here once a position returns to flat.'}
        />
      ) : (
        <ul>{rows.map((trade) => <Record key={trade.id} trade={trade} open={tab === 'OPEN'} />)}</ul>
      )}
    </Card>
  );
};

export default TradeLedger;
