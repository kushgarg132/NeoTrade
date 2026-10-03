import React from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Money, NetLine, Ruling, Empty } from '../doc/Doc';
import { formatQuantity, formatPercent } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * Real money: the round trips the user's own broker reported, as imported
 * into the journal. Gross of charges, like the journal it comes from, and
 * only as fresh as the last sync -- so it says so rather than implying a
 * live feed.
 */

const BROKER_NAMES = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const todayIst = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());

const Line = ({ label, children, muted }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5">
    <span className={cn('text-sm', muted ? 'text-[var(--ink-faint)]' : 'text-[var(--ink-soft)]')}>
      {label}
    </span>
    <span className="figure-md text-sm tabular-nums">{children}</span>
  </div>
);

const BrokerPnl = ({ journal, loading, error }) => {
  if (loading) {
    return (
      <Sheet title="Your broker">
        <Ruling rows={2} />
      </Sheet>
    );
  }

  const connected = journal?.brokers_connected || [];
  if (!error && journal && journal.calendar.length === 0 && connected.length > 0) {
    const names = connected.map((b) => BROKER_NAMES[b] || b).join(' and ');
    return (
      <Sheet title="Your broker account">
        <Empty
          title={`${names} connected`}
          detail="No trades imported yet. Each trading day's trades import after the market closes. For Upstox, Import Upstox history in the journal brings in the past year."
          action={
            <Link to="/journal" className="field-label text-[var(--stamp)] hover:underline">
              Open the journal
            </Link>
          }
        />
      </Sheet>
    );
  }

  if (error || !journal || journal.calendar.length === 0) {
    return (
      <Sheet title="Your broker account">
        <Empty
          title={error ? 'Could not load your trades' : 'No broker trades yet'}
          detail={
            error ||
            'Connect your broker in Settings and your real trades import into the journal on their own. The figures here come from there.'
          }
          action={
            <Link to={error ? '/journal' : '/settings'} className="field-label text-[var(--stamp)] hover:underline">
              {error ? 'Open the journal' : 'Connect a broker'}
            </Link>
          }
        />
      </Sheet>
    );
  }

  const today = todayIst();
  const month = today.slice(0, 7);
  const todayRow = journal.calendar.find((row) => row.day === today);
  const monthRows = journal.calendar.filter((row) => row.day.startsWith(month));
  const monthPnl = monthRows.reduce((total, row) => total + row.pnl, 0);
  const monthTrips = monthRows.reduce((total, row) => total + row.trips, 0);
  const monthWins = monthRows.reduce((total, row) => total + (row.wins || 0), 0);
  const best = monthRows.length ? Math.max(...monthRows.map((row) => row.pnl)) : null;
  const worst = monthRows.length ? Math.min(...monthRows.map((row) => row.pnl)) : null;

  return (
    <Sheet title="Your broker" meta="Gross · last journal sync">
      <div className="grid grid-cols-2 divide-x divide-[var(--rule)]">
        <div className="pr-3 min-w-0">
          <p className="field-label mb-1">Today</p>
          <Money value={todayRow?.pnl || 0} className="text-xl" />
          <p className="doc-meta normal-case mt-1">
            {formatQuantity(todayRow?.trips || 0)} closed
            {todayRow?.trips > 0 && ` · ${todayRow.wins} won`}
          </p>
        </div>
        <div className="pl-3 min-w-0">
          <p className="field-label mb-1">This month</p>
          <Money value={monthPnl} className="text-xl" />
          <p className="doc-meta normal-case mt-1">
            {formatQuantity(monthTrips)} closed
            {monthTrips ? ` · ${formatPercent((monthWins / monthTrips) * 100)} won` : ''}
          </p>
        </div>
      </div>
      {best !== null && (
        <p className="doc-meta normal-case pt-2 mt-2 border-t border-[var(--rule)]">
          Best day <Money value={best} size="sm" className="text-xs" /> · worst <Money value={worst} size="sm" className="text-xs" />
        </p>
      )}
    </Sheet>
  );
};

export default BrokerPnl;
