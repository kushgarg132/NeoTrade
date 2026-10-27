import React, { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import Stat from '../components/ui/Stat';
import Badge from '../components/ui/Badge';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Empty from '../components/ui/Empty';
import TradingChart from '../components/stock/TradingChart';
import useStockAnalysis from '../components/stock/useStockAnalysis';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { tradeSummary } from '../utils/aiDetail';
import { stockPath } from '../utils/stocks';
import { strategyPath } from '../utils/routes';
import { strategyName } from '../utils/library';
import { formatDateTime } from '../utils/formatters';
import { inr } from '../components/ui/format';

const day = (v) => String(v).slice(0, 10);

/** /ai/trade/:id: one AI paper trade, from entry to exit, with the signal behind it. */
const AiTrade = () => {
  const id = useParams().id;
  const trade = useStored(endpoints.trade(id));
  const t = trade.data;
  const { quick } = useStockAnalysis(t?.symbol);

  const closes = useMemo(
    () => (quick.data?.price_data || []).map((c) => ({ date: day(c.timestamp), close: Number(c.close) })),
    [quick.data],
  );
  const markers = useMemo(() => {
    if (!t) return [];
    const out = [{ date: day(t.entry_at), side: t.side, price: t.entry_price }];
    if (t.exit_at) out.push({ date: day(t.exit_at), side: t.side === 'BUY' ? 'SELL' : 'BUY', price: t.exit_price });
    return out;
  }, [t]);

  if (trade.status === 'empty') {
    return (
      <Layout>
        <PageHeader title="Not found" back="/ai" backLabel="AI" />
        <Empty title="Not found" body="This trade doesn't exist." action={<Link to="/ai" className="inline-flex items-center min-h-11 px-4 text-[15px] font-semibold text-[var(--accent)]">Back to AI</Link>} />
      </Layout>
    );
  }
  if (trade.status !== 'ok') {
    return (
      <Layout>
        <PageHeader title="Trade" back="/ai" backLabel="AI" />
        {trade.status === 'loading' ? <Skeleton rows={5} /> : <ErrorLine message="Couldn't load this trade." onRetry={trade.retry} />}
      </Layout>
    );
  }

  const s = tradeSummary(t);
  const c = t.context || {};
  const score = c.score;
  const levels = [
    c.stop != null && ['Stop', inr(c.stop)],
    c.target != null && ['Target', inr(c.target)],
    c.max_hold_days != null && ['Max hold', `${c.max_hold_days}d`],
    c.trail_atr != null && ['Trail', `${c.trail_atr} x ATR`],
  ].filter(Boolean);

  return (
    <Layout>
      <PageHeader
        title={`${t.symbol} · ${t.side}`}
        back={t.strategy ? strategyPath(t.strategy) : '/ai'}
        backLabel={t.strategy ? strategyName(t.strategy) : 'AI'}
        right={t.venue === 'live' ? <Badge kind="live">Live</Badge> : <Badge kind="paper">Paper</Badge>}
      />
      <div className="space-y-3">
        {!s.open && <Hero label="Net" value={s.net} format={(v) => inr(v, { sign: true })} />}
        <Card title="Result" action={s.open ? <Badge kind="neutral">Open</Badge> : null}>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Entry" value={`${inr(t.entry_price)}`} delta={formatDateTime(t.entry_at)} />
            <Stat label="Exit" value={s.open ? 'Open' : inr(t.exit_price)} delta={s.open ? null : formatDateTime(t.exit_at)} />
            <Stat label="Quantity" value={t.quantity} />
            <Stat label="Held" value={s.held} />
            {!s.open && <Stat label="Gross" value={inr(s.gross, { sign: true })} />}
            <Stat label="Costs" value={inr(s.costs)} />
            {t.exit_reason && <Stat label="Exit reason" value={t.exit_reason} />}
          </div>
          <Link to={stockPath(t.symbol)} className="mt-3 inline-flex items-center min-h-11 text-[15px] font-semibold text-[var(--accent)]">Open {t.symbol}</Link>
        </Card>

        <Card title="Chart">
          {closes.length >= 2 ? (
            <TradingChart closes={closes} trades={markers} thesis={{ stop: c.stop, target: c.target }} symbol={t.symbol} initialRange="1Y" />
          ) : quick.loading ? <Skeleton rows={5} /> : <Empty title="No price data" body={`Price history for ${t.symbol} appears here.`} />}
        </Card>

        <Card title="Why it traded">
          {levels.length === 0 && !c.reason_codes?.length && !score ? (
            <Empty title="No signal recorded" body="Trades opened by the engine store their stop, target and reasons here." />
          ) : (
            <>
              {levels.length > 0 && (
                <div className="grid grid-cols-2 gap-3 mb-3">{levels.map(([l, v]) => <Stat key={l} label={l} value={v} />)}</div>
              )}
              {score && (
                <p className="text-[14px] text-[var(--text)] mb-2">
                  Score: rules {score.rule?.toFixed?.(2) ?? '–'} · AI {score.ai?.toFixed?.(2) ?? '–'} · final {score.final?.toFixed?.(2) ?? '–'}
                </p>
              )}
              {c.reason_codes?.length > 0 && (
                <div className="flex flex-wrap gap-2">{c.reason_codes.map((r) => <Badge key={r} kind="neutral">{r}</Badge>)}</div>
              )}
            </>
          )}
        </Card>
      </div>
    </Layout>
  );
};

export default AiTrade;
