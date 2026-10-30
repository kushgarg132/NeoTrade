import React from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import Badge from '../ui/Badge';
import { inr } from '../ui/format';
import { formatCurrency, formatTimeAgo } from '../../utils/formatters';
import { countdown, daysUntil, dividendRows, eventTitle, sourceOf, todayIst } from '../../utils/events';
import { day } from './common';

const Row = ({ title, sub, right }) => (
  <li className="flex items-start justify-between gap-3 py-2.5 border-b border-[var(--border)] last:border-b-0">
    <div className="min-w-0">
      <div className="text-[15px] font-medium text-[var(--text)]">{title}</div>
      {sub && <div className="text-[13px] text-[var(--text-muted)]">{sub}</div>}
    </div>
    {right && <div className="shrink-0 text-right">{right}</div>}
  </li>
);

/** A calendar leaf: "12 / NOV". */
const DateLeaf = ({ date }) => {
  const d = new Date(`${date}T00:00:00Z`);
  return (
    <div className="w-12 shrink-0 rounded-[10px] bg-[var(--accent-soft)] py-1 text-center">
      <div className="text-[17px] font-bold leading-tight tabular-nums text-[var(--text)]">{d.getUTCDate()}</div>
      <div className="text-[11px] font-semibold uppercase text-[var(--accent)]">{d.toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })}</div>
    </div>
  );
};

/** Coming up (with a countdown and, for a dividend, your payout), news events from the AI read, the
 *  dividend history with what you got, and recent results dates. */
const EventsTab = ({ mine, ai }) => {
  const today = todayIst();
  const qty = mine?.position?.qty || 0;
  const upcoming = mine?.events || [];
  const notable = [...(ai?.data?.events || [])].sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const { rows: divs, total } = dividendRows(mine?.past_events?.dividends, mine?.dividends);
  const results = mine?.past_events?.results || [];
  if (!upcoming.length && !notable.length && !divs.length && !results.length)
    return <Empty title="Nothing scheduled" body="Results, dividends and board meetings show here when they are announced." />;
  return (
    <div className="space-y-3">
      {upcoming.length > 0 && (
        <Card title="Coming up">
          <ul>
            {upcoming.map((e, i) => {
              const payout = e.kind === 'ex_dividend' && e.amount != null && qty > 0 ? e.amount * qty : null;
              return (
                <li key={i} className="flex items-center gap-3 py-2.5 border-b border-[var(--border)] last:border-b-0">
                  <DateLeaf date={e.date} />
                  <div className="min-w-0">
                    <div className="text-[15px] font-medium text-[var(--text)]">{eventTitle(e)}</div>
                    <div className="text-[13px] text-[var(--text-muted)]">
                      {[countdown(daysUntil(e.date, today)), e.amount != null && `${formatCurrency(e.amount)} a share`].filter(Boolean).join(' · ')}
                    </div>
                    {payout != null && <div className="private text-[13px] text-[var(--gain)]">About {inr(payout)} for your {qty} shares, if you hold them the day before</div>}
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {notable.length > 0 && (
        <Card title="In the news">
          <ul>
            {notable.map((e, i) => (
              <Row key={i} title={e.event_type}
                   sub={[e.date && formatTimeAgo(e.date), sourceOf(e.description)].filter(Boolean).join(' · ')}
                   right={e.impact_rating != null && <Badge kind={e.impact_rating >= 6 ? 'alert' : 'neutral'}>Impact {e.impact_rating}/10</Badge>} />
            ))}
          </ul>
        </Card>
      )}

      {divs.length > 0 && (
        <Card title="Dividends" action={total > 0 ? <span className="private text-[15px] font-semibold text-[var(--gain)]">{inr(total)} received</span> : null}>
          <ul>
            {divs.map((d) => (
              <Row key={d.date} title={day(d.date)} sub={d.perShare != null ? `${formatCurrency(d.perShare)} a share` : null}
                   right={d.amount != null
                     ? <span className="private text-[15px] font-semibold text-[var(--text)]">{inr(d.amount)}<span className="block text-[12px] font-normal text-[var(--text-muted)]">on {d.qty} shares</span></span>
                     : <span className="text-[13px] text-[var(--text-muted)]">Not held</span>} />
            ))}
          </ul>
        </Card>
      )}

      {results.length > 0 && (
        <Card title="Recent results">
          <ul>
            {results.map((d) => <Row key={d} title={day(d)} sub={countdown(daysUntil(d, today))} />)}
          </ul>
        </Card>
      )}
    </div>
  );
};

export default EventsTab;
