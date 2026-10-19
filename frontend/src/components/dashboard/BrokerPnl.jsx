import React from 'react';
import { Link } from 'react-router-dom';
import Card from '../ui/Card';
import Stat from '../ui/Stat';
import Empty from '../ui/Empty';
import Skeleton from '../ui/Skeleton';
import { inr, tone } from '../ui/format';
import { formatQuantity, formatPercent } from '../../utils/formatters';

/**
 * Real money: the round trips the user's own broker reported, as imported into the journal.
 * Gross of charges, and only as fresh as the last sync -- so it says so rather than implying a live feed.
 */
const BROKER_NAMES = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };
const todayIst = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
const linkCls = 'inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]';

const BrokerPnl = ({ journal, loading, error }) => {
  if (loading) return <Card title="Your broker"><Skeleton rows={2} /></Card>;

  const connected = journal?.brokers_connected || [];
  if (!error && journal && journal.calendar.length === 0 && connected.length > 0) {
    const names = connected.map((b) => BROKER_NAMES[b] || b).join(' and ');
    return (
      <Card title="Your broker account">
        <Empty
          title={`${names} connected`}
          body="No trades imported yet. Each trading day's trades import after the market closes. For Upstox, Import Upstox history in the journal brings in the past year."
        />
      </Card>
    );
  }

  if (error || !journal || journal.calendar.length === 0) {
    return (
      <Card title="Your broker account">
        <Empty
          title={error ? 'Could not load your trades' : 'No broker trades yet'}
          body={error || 'Connect your broker in Settings and your real trades import into the journal on their own. The figures here come from there.'}
          action={!error && <Link to="/settings?tab=accounts" className={linkCls}>Connect a broker</Link>}
        />
      </Card>
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
    <Card title="Your broker" action={<span className="text-[13px] text-[var(--text-muted)]">Gross · last sync</span>}>
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Today" value={inr(todayRow?.pnl || 0, { sign: true })} tone={tone(todayRow?.pnl)}
              delta={`${formatQuantity(todayRow?.trips || 0)} closed${todayRow?.trips > 0 ? ` · ${todayRow.wins} won` : ''}`} />
        <Stat label="This month" value={inr(monthPnl, { sign: true })} tone={tone(monthPnl)}
              delta={`${formatQuantity(monthTrips)} closed${monthTrips ? ` · ${formatPercent((monthWins / monthTrips) * 100)} won` : ''}`} />
      </div>
      {best !== null && (
        <p className="private mt-3 pt-3 border-t border-[var(--border)] text-[13px] text-[var(--text-muted)]">
          Best day {inr(best, { sign: true })} · worst {inr(worst, { sign: true })}
        </p>
      )}
    </Card>
  );
};

export default BrokerPnl;
