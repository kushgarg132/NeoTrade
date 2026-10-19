import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Empty from '../components/ui/Empty';
import { inr, pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import OrderTicket from '../components/trading/OrderTicket';
import TradingChart from '../components/stock/TradingChart';
import NewsTab from '../components/stock/NewsTab';
import AnalysisTab from '../components/stock/AnalysisTab';
import EventsTab from '../components/stock/EventsTab';
import useStockAnalysis from '../components/stock/useStockAnalysis';
import { verdictKind, verdictLabel } from '../components/stock/common';
import api, { endpoints } from '../utils/api';
import { bareSymbol, formatQuantity } from '../utils/formatters';
import { positionSummary } from '../utils/stock';

const TABS = [
  { id: 'chart', label: 'Chart' },
  { id: 'news', label: 'News' },
  { id: 'analysis', label: 'Analysis' },
  { id: 'events', label: 'Events' },
];

const Stat = ({ label, value, valueClass = '' }) => (
  <div className="min-w-0">
    <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
    <div className={`private text-[15px] font-semibold tabular-nums truncate ${valueClass}`}>{value}</div>
  </div>
);

/** /stock/:symbol: price and verdict on top, your position if you hold it, then Chart / News / Analysis / Events. */
const Stock = () => {
  const symbol = bareSymbol(useParams().symbol)?.toUpperCase();
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id));
  const { quick, ai, requestAi, reloadQuick } = useStockAnalysis(symbol);

  // Your side of the stock: 404 means you have never held it, which is not an error.
  const [mineRaw, setMine] = useState({ data: null, status: 'loading', symbol }); // loading | ok | missing | error
  const mine = mineRaw.symbol === symbol ? mineRaw : { data: null, status: 'loading' }; // another stock's answer is not ours
  const [portfolio, setPortfolio] = useState(null);
  const [ticket, setTicket] = useState(null);
  const loadMine = useCallback(() => {
    api
      .get(endpoints.mine.stock(symbol))
      .then((res) => setMine({ data: res.data, status: 'ok', symbol }))
      .catch((err) => setMine({ data: null, status: err?.response?.status === 404 ? 'missing' : 'error', symbol }));
  }, [symbol]);
  useEffect(loadMine, [loadMine]);
  useEffect(() => {
    api.get(endpoints.mine.overview).then((res) => setPortfolio(res.data?.headline?.value ?? null)).catch(() => setPortfolio(null));
  }, []);

  const m = mine.data;
  const company = quick.data?.company_info;
  const currency = company?.currency || 'INR';
  const closes = useMemo(() => {
    const fromQuick = (quick.data?.price_data || []).map((c) => ({ date: String(c.timestamp).slice(0, 10), close: Number(c.close) }));
    return (m?.closes?.length || 0) > fromQuick.length ? m.closes : fromQuick; // the longer history wins (5Y)
  }, [quick.data, m]);

  const price = company?.current_price ?? closes.at(-1)?.close;
  const prev = company?.previous_close;
  const dayPct = company?.day_change_percent != null ? company.day_change_percent / 100 : prev ? price / prev - 1 : null;
  const dayAbs = prev != null && price != null ? price - prev : null;
  const pos = positionSummary(m?.position, portfolio);
  const verdict = m?.verdict?.current;
  const sold = m?.position?.sold;

  const panel = {
    chart: closes.length >= 2 || !quick.loading ? (
      <Card>
        <TradingChart closes={closes} trades={m?.trades} thesis={m?.thesis} symbol={symbol} currency={currency} />
      </Card>
    ) : <Card><Skeleton rows={5} /></Card>,
    news: <NewsTab mine={m} ai={ai} onAnalysis={() => setTab('analysis')} />,
    analysis: <AnalysisTab symbol={symbol} mine={m} quick={quick} ai={ai} requestAi={requestAi} onThesis={(t) => setMine((s) => ({ ...s, data: { ...s.data, thesis: t } }))} />,
    events: <EventsTab mine={m} ai={ai} />,
  }[tab];

  return (
    <Layout>
      <PageHeader title={symbol} back right={verdict && !sold ? <Badge kind={verdictKind(verdict)}>{verdictLabel(verdict)}</Badge> : null} />

      <Card className="mb-3">
        {quick.loading && price == null ? (
          <Skeleton rows={2} />
        ) : quick.error && price == null ? (
          <ErrorLine message={quick.error} onRetry={reloadQuick} />
        ) : (
          <>
            {company?.name && <p className="text-[14px] text-[var(--text-muted)] truncate">{company.name}</p>}
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[28px] leading-9 font-bold tabular-nums text-[var(--text)]">{currency === 'INR' ? inr(price) : price}</span>
              {dayPct != null && (
                <span className={`text-[15px] font-semibold tabular-nums ${toneText(tone(dayPct))}`}>
                  {dayAbs != null && currency === 'INR' && `${inr(dayAbs, { sign: true })} `}({pct(dayPct, { sign: true })}) today
                </span>
              )}
            </div>
          </>
        )}
        {pos && (
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="You hold" value={`${formatQuantity(pos.qty)} · avg ${inr(pos.avg)}`} />
              <Stat
                label="Gain"
                value={`${inr(pos.pnl, { sign: true })}${pos.pnlPct != null ? ` (${pct(pos.pnlPct, { sign: true, dp: 1 })})` : ''}`}
                valueClass={toneText(tone(pos.pnl))}
              />
            </div>
            {pos.weight != null && <p className="mt-2 text-[13px] text-[var(--text-muted)]">{pct(pos.weight, { dp: 1 })} of your portfolio</p>}
          </div>
        )}
        {sold && <p className="mt-3 text-[14px] text-[var(--text-muted)]">You no longer hold this. Past trades are on the chart.</p>}
        {mine.status === 'error' && <ErrorLine message="Could not load your position." onRetry={loadMine} />}
      </Card>

      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Stock sections" />
      <div className="mt-3">
        {tab === 'chart' && quick.error && !closes.length ? <Empty title="No price data" body={quick.error} action={<Button variant="secondary" onClick={reloadQuick}>Retry</Button>} /> : panel}
      </div>

      <div className="h-28 lg:h-20" aria-hidden="true" />
      <div className="fixed z-30 inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 lg:left-56 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <div className="mx-auto max-w-5xl flex gap-3">
          {pos && <Button variant="secondary" className="flex-1" onClick={() => setTicket({ symbol, side: 'SELL', lastPrice: price })}>Sell</Button>}
          <Button className="flex-1" disabled={price == null} onClick={() => setTicket({ symbol, side: 'BUY', lastPrice: price })}>{pos ? 'Buy more' : 'Buy'}</Button>
        </div>
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={loadMine} />}
    </Layout>
  );
};

export default Stock;
