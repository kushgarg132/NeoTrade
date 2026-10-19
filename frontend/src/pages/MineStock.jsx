import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceDot, ReferenceLine } from 'recharts';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { PORTFOLIO_TABS } from '../components/layout/sections';
import { StockAnalysis } from './Dashboard';
import { Sheet, Field, Money, Empty, Ruling, Scrip, Stamp, Statement, Row, Cell } from '../components/doc/Doc';
import ThesisEditor from '../components/mine/ThesisEditor';
import OrderTicket, { TicketButton } from '../components/trading/OrderTicket';
import api, { endpoints } from '../utils/api';
import { REASONS, formatXirr } from '../utils/mine';
import { bareSymbol, formatCurrency, formatPercent, formatQuantity, formatTimeAgo } from '../utils/formatters';

const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const day = (d) => (d ? new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—');
const TONE = { SELL: 'loss', REVIEW: 'loss', ADD: 'gain' };

// Buys are filled circles, sells hollow squares: identity is never colour alone.
const Buy = ({ cx, cy }) => <circle cx={cx} cy={cy} r={5} fill="var(--gain)" stroke="var(--paper)" strokeWidth={2} />;
const Sell = ({ cx, cy }) => <rect x={cx - 4.5} y={cy - 4.5} width={9} height={9} fill="var(--paper)" stroke="var(--loss)" strokeWidth={2} />;

// A trade date with no close that day (holiday, import gap) snaps to the last close before it.
const snap = (closes, date) => {
  let hit = null;
  for (const c of closes) if (c.date <= date) hit = c;
  return hit;
};

const PriceChart = ({ closes, trades, thesis }) => {
  const dots = (trades || [])
    .map((t) => ({ ...t, at: snap(closes, t.date) }))
    .filter((t) => t.at);
  const lines = [
    thesis?.target != null && { y: thesis.target, label: `Target ${formatCurrency(thesis.target)}`, color: 'var(--gain)' },
    thesis?.stop != null && { y: thesis.stop, label: `Stop ${formatCurrency(thesis.stop)}`, color: 'var(--loss)' },
  ].filter(Boolean);
  const last = closes.at(-1);
  return (
    <>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 mb-2 text-xs text-[var(--ink-soft)]">
        <li className="inline-flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="var(--ink)" strokeWidth="2" /></svg>
          Close
        </li>
        <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Buy cx={5} cy={5} /></svg>Your buys</li>
        <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Sell cx={5} cy={5} /></svg>Your sells</li>
        {lines.map((l) => (
          <li key={l.label} className="inline-flex items-center gap-1.5">
            <svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke={l.color} strokeWidth="2" strokeDasharray="5 4" /></svg>
            {l.label}
          </li>
        ))}
      </ul>
      <div className="h-56 sm:h-72" role="img" aria-label={`Daily closes, last ${formatCurrency(last.close)}, with ${dots.length} of your trades marked`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={closes} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--rule)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={short} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} minTickGap={40} tickLine={false} axisLine={{ stroke: 'var(--rule-strong)' }} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} width={44} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
            <Tooltip
              formatter={(v) => [formatCurrency(v), 'Close']}
              labelFormatter={short}
              contentStyle={{ background: 'var(--paper)', border: '1px solid var(--rule-strong)', fontSize: 12 }}
            />
            <Line type="monotone" dataKey="close" stroke="var(--ink)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            {lines.map((l) => (
              <ReferenceLine key={l.label} y={l.y} stroke={l.color} strokeWidth={2} strokeDasharray="5 4" ifOverflow="extendDomain" />
            ))}
            {dots.map((t, i) => (
              <ReferenceDot key={i} x={t.at.date} y={t.price ?? t.at.close} shape={t.side === 'SELL' ? Sell : Buy} ifOverflow="extendDomain" />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
};

const LOT_COLUMNS = [
  { key: 'buy', label: 'Bought' },
  { key: 'qty', label: 'Qty', align: 'right' },
  { key: 'price', label: 'Price', align: 'right' },
  { key: 'lt', label: 'Long-term in', align: 'right' },
  { key: 'gain', label: 'Gain', align: 'right' },
  { key: 'tax', label: 'Tax if sold today', align: 'right' },
];

/** Mine → Stock: one holding, with your trades, your thesis and the verdict's history. */
const MineStock = () => {
  const { symbol: raw } = useParams();
  const symbol = bareSymbol(raw)?.toUpperCase();
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ok | missing | error
  const [ticket, setTicket] = useState(null);

  const load = useCallback(() => {
    api
      .get(endpoints.mine.stock(symbol))
      .then((res) => (setData(res.data), setStatus('ok')))
      .catch((err) => setStatus(err?.response?.status === 404 ? 'missing' : 'error'));
  }, [symbol]);
  useEffect(() => {
    setStatus('loading');
    load();
  }, [load]);

  const p = data?.position;
  const v = data?.verdict;
  const lastClose = data?.closes?.at(-1)?.close;
  const dividends = data?.dividends || [];
  const events = data?.events || [];
  const news = data?.news || [];

  let body;
  if (status === 'loading') body = <Sheet><Ruling rows={6} /></Sheet>;
  // Not held: skip the position blocks and show the analysis alone.
  else if (status === 'missing') body = null;
  else if (status === 'error') body = <Sheet title={symbol}><Empty title="Could not load this stock" /></Sheet>;
  else
    body = (
      <>
        <Sheet
          title={<Scrip symbol={symbol} icon={false} />}
          meta={p?.sold ? undefined : p?.held_since ? `Held since ${day(p.held_since)}` : undefined}
          actions={
            <div className="flex items-center gap-2">
              {!p?.sold && <TicketButton label="Add" onClick={() => setTicket({ symbol, side: 'BUY', lastPrice: lastClose })} />}
              {!p?.sold && <TicketButton label="Sell" tone="loss" onClick={() => setTicket({ symbol, side: 'SELL', lastPrice: lastClose })} />}
            </div>
          }
        >
          {p?.sold ? (
            <div className="flex items-center gap-3">
              <Stamp label="Sold" tone="loss" />
              <span className="text-sm text-[var(--ink-soft)]">You no longer hold this. Past trades and lots are below.</span>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-4 gap-y-3">
              <Field label="Quantity" value={formatQuantity(p?.qty)} />
              <Field label="Avg cost" value={formatCurrency(p?.avg_price)} />
              <Field label="Value" value={formatCurrency(p?.value)} />
              <Field label="Gain" value={<Money value={p?.pnl} size="sm" />} />
              <Field label="Gain %" value={p?.pnl_pct == null ? '—' : formatPercent(p.pnl_pct)} />
              <Field label="XIRR" value={formatXirr(p?.xirr)} />
            </div>
          )}
          {data.lots?.length > 0 && (
            <div className="mt-4">
              <Statement columns={LOT_COLUMNS}>
                {data.lots.map((l, i) => (
                  <Row key={i}>
                    <Cell>{day(l.buy_date)}</Cell>
                    <Cell align="right" mono>{formatQuantity(l.qty)}</Cell>
                    <Cell align="right" mono>{formatCurrency(l.price)}</Cell>
                    <Cell align="right">{l.days_to_long > 0 ? `${l.days_to_long} days` : 'Long-term'}</Cell>
                    <Cell align="right"><Money value={l.gain} size="sm" /></Cell>
                    <Cell align="right" mono>{formatCurrency(l.est_tax)}</Cell>
                  </Row>
                ))}
              </Statement>
              <p className="doc-meta normal-case mt-2">Tax is an estimate, not tax advice.</p>
            </div>
          )}
          {data.unknown_qty > 0 && (
            <p className="doc-meta normal-case mt-2">{formatQuantity(data.unknown_qty)} shares have no known buy date and are left out of the lots.</p>
          )}
        </Sheet>

        <Sheet title="Price and your trades">
          {data.closes?.length >= 2 ? (
            <PriceChart closes={data.closes} trades={data.trades} thesis={data.thesis} />
          ) : (
            <Empty title="No price history yet" />
          )}
        </Sheet>

        <Sheet title="Your thesis">
          <ThesisEditor symbol={symbol} thesis={data.thesis} onSaved={(t) => setData((d) => ({ ...d, thesis: t }))} />
        </Sheet>

        <Sheet title="Verdict" meta={v?.current ? undefined : 'None yet'}>
          {v?.current && (
            <div className="space-y-2">
              <Stamp label={v.current === 'REVIEW' ? 'Review first' : v.current} tone={TONE[v.current] || 'stamp'} />
              {v.reasons?.length > 0 && (
                <ul className="text-sm space-y-0.5">
                  {v.reasons.map((code) => (
                    <li key={code} className="text-[var(--ink-soft)]">· {REASONS[code] || code.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
              )}
              {v.note && <p className="text-sm">{v.note}</p>}
            </div>
          )}
          {v?.history?.length > 0 && (
            <div className="mt-4">
              <p className="field-label mb-1">How it changed</p>
              <ul>
                {[...v.history].reverse().map((h, i) => (
                  <li key={i} className="flex justify-between py-1.5 border-b border-[var(--rule)] text-sm">
                    <span className="text-[var(--ink-soft)]">{day(h.date)}</span>
                    <span className="font-semibold">{h.verdict === 'REVIEW' ? 'Review first' : h.verdict}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Sheet>

        <Sheet title="Coming up">
          {events.length === 0 ? (
            <p className="text-sm text-[var(--ink-faint)]">Nothing scheduled.</p>
          ) : (
            <ul>
              {events.map((e, i) => (
                <li key={i} className="flex justify-between gap-3 py-1.5 border-b border-[var(--rule)] text-sm">
                  <span>{String(e.label || e.type || e.kind || 'Event').replace(/_/g, ' ')}{e.amount != null && ` · ${formatCurrency(e.amount)} a share`}</span>
                  <span className="text-[var(--ink-soft)]">{day(e.date)}</span>
                </li>
              ))}
            </ul>
          )}
        </Sheet>

        <Sheet title="Dividends received" meta="Estimated from ex-dates and what you held">
          {dividends.length === 0 ? (
            <p className="text-sm text-[var(--ink-faint)]">None yet.</p>
          ) : (
            <ul>
              {dividends.map((d, i) => (
                <li key={i} className="flex justify-between py-1.5 border-b border-[var(--rule)] text-sm">
                  <span className="text-[var(--ink-soft)]">{day(d.date)}</span>
                  <span className="figure-md">{formatCurrency(d.total ?? d.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </Sheet>

        <Sheet title="News">
          {news.length === 0 ? (
            <p className="text-sm text-[var(--ink-faint)]">No scored headlines.</p>
          ) : (
            <ul>
              {news.map((n, i) => (
                <li key={n.id || i} className="py-1.5 border-b border-[var(--rule)] text-sm">
                  {n.url ? <a href={n.url} target="_blank" rel="noreferrer" className="hover:text-[var(--stamp)]">{n.headline || n.title}</a> : (n.headline || n.title)}
                  {(n.published_at || n.published) && <span className="doc-meta normal-case ml-2">{formatTimeAgo(n.published_at || n.published)}</span>}
                </li>
              ))}
            </ul>
          )}
        </Sheet>
      </>
    );

  return (
    <Layout>
      <div className="space-y-3">
        <SectionTabs tabs={PORTFOLIO_TABS} label="Portfolio" />
        {body}
        <StockAnalysis symbol={symbol} />
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={load} />}
    </Layout>
  );
};

export default MineStock;
