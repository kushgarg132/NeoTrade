import React from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Money, NetLine, Ruling, Empty } from '../doc/Doc';
import { formatQuantity, formatPercent, formatNoteDate } from '../../utils/formatters';
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
      <div className="grid gap-4 sm:grid-cols-2">
        <Sheet title="Today · your broker">
          <Ruling rows={3} />
        </Sheet>
        <Sheet title="Month to date">
          <Ruling rows={3} />
        </Sheet>
      </div>
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
    <div className="grid gap-4 sm:grid-cols-2">
      <Sheet title="Today · your broker" meta={formatNoteDate()}>
        <Line label="Round trips closed" muted>
          {formatQuantity(todayRow?.trips || 0)}
          {todayRow?.trips > 0 && (
            <span className="text-[var(--ink-faint)]">
              {' '}
              ({todayRow.wins} won)
            </span>
          )}
        </Line>
        <p className="doc-meta normal-case pt-1">
          Gross of charges · as of the last journal sync
        </p>
        <NetLine label="Net today">
          <Money value={todayRow?.pnl || 0} size="lg" />
        </NetLine>
      </Sheet>

      <Sheet title="Month to date">
        <Line label="Round trips closed" muted>
          {formatQuantity(monthTrips)}
        </Line>
        <Line label="Strike rate" muted>
          {monthTrips ? formatPercent((monthWins / monthTrips) * 100) : '—'}
        </Line>
        <Line label="Best / worst day">
          {best === null ? (
            '—'
          ) : (
            <>
              <Money value={best} />
              <span className="text-[var(--ink-faint)]"> / </span>
              <Money value={worst} />
            </>
          )}
        </Line>
        <NetLine label="Net this month">
          <Money value={monthPnl} />
        </NetLine>
      </Sheet>
    </div>
  );
};

export default BrokerPnl;
