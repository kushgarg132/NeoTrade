import React, { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import Stat from '../components/ui/Stat';
import ListRow from '../components/ui/ListRow';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import { NewsChips, TripHeadlines, NoteEditor } from '../components/money/JournalTab';
import { useLoad } from '../components/ideas/useLoad';
import api, { endpoints } from '../utils/api';
import { stockPath } from '../utils/stocks';
import { holdTime } from '../utils/roundTrip';
import { inr } from '../components/ui/format';
import { formatQuantity, formatDateTime } from '../utils/formatters';
import { px } from '../components/ideas/levels';

const BACK = '/money?tab=journal';

const avg = (fills, side) => {
  const f = fills.filter((x) => x.side === side);
  const qty = f.reduce((t, x) => t + x.quantity, 0);
  return qty ? f.reduce((t, x) => t + x.quantity * x.price, 0) / qty : null;
};

const Body = ({ trip, reload }) => {
  const fills = trip.fills || [];
  const open = trip.pnl === null;
  const long = trip.direction !== 'SHORT';
  const entry = avg(fills, long ? 'BUY' : 'SELL') ?? trip.entry_price;
  const exit = avg(fills, long ? 'SELL' : 'BUY') ?? trip.exit_price;
  return (
    <div className="space-y-4">
      {!open && <Hero label="P&L" value={trip.pnl} format={(v) => inr(v, { sign: true })} />}
      <Card title={`${trip.symbol} · ${long ? 'Long' : 'Short'}`} action={<Link to={stockPath(trip.symbol)} className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">View stock</Link>}>
        <div className="grid grid-cols-2 gap-4">
          {open && <div className="private"><Stat label="P&L" value="Open" /></div>}
          <Stat label="Held" value={holdTime(trip.opened_at, trip.closed_at)} />
          <div className="private"><Stat label="Average entry" value={px(entry)} /></div>
          <div className="private"><Stat label="Average exit" value={px(exit)} /></div>
        </div>
        <div className="mt-3"><NewsChips trip={trip} /></div>
      </Card>

      <Card title="Fills">
        <div className="private">
          {fills.map((f, i) => (
            <ListRow key={i} chevron={false} title={`${f.side === 'BUY' ? 'Bought' : 'Sold'} ${formatQuantity(f.quantity)}`} sub={formatDateTime(f.traded_at)} right={px(f.price)} />
          ))}
        </div>
      </Card>

      <Card title="Note">
        <TripHeadlines trip={trip} />
        <div className="private"><NoteEditor trip={trip} onSaved={reload} /></div>
      </Card>

      <Card title="Patterns this trade is part of">
        {(trip.insights || []).length === 0 ? (
          <Empty title="No pattern includes this trade" body="A pattern shows once it covers at least 5 closed trades." />
        ) : (
          <ul>
            {trip.insights.map((f) => (
              <li key={`${f.kind}:${f.title}`} className="py-3 border-b border-[var(--border)] last:border-b-0">
                <p className="text-[15px] text-[var(--text)]">{f.title}</p>
                <p className="text-[13px] text-[var(--text-muted)] mt-1">{f.trips} trades{f.note ? ` · ${f.note}` : ''}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
};

const RoundTrip = () => {
  const { id } = useParams();
  const load = useCallback(
    () => api.get(endpoints.roundTrip(id)).then((r) => r.data).catch((err) => {
      if (err?.response?.status === 404) return { notFound: true };
      throw err;
    }),
    [id]
  );
  const { data, error, loading, reload } = useLoad(load);
  let body;
  if (loading && !data) body = <Card><Skeleton rows={6} /></Card>;
  else if (error) body = <Card><ErrorLine message="Could not load this trade." onRetry={reload} /></Card>;
  else if (data?.notFound) {
    body = <Empty title="Not found" body="This trade is not in your journal." action={<Link to={BACK} className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">Back to the journal</Link>} />;
  } else body = <Body trip={data} reload={reload} />;
  return (
    <Layout>
      <PageHeader title={data?.symbol || 'Trade'} back={BACK} backLabel="Journal" />
      {body}
    </Layout>
  );
};

export default RoundTrip;
