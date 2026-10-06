import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import { paperPositions } from '../utils/books';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import { Badge } from '../components/common/Badge';
import { periodSummary } from '../utils/practice';
import OrderTicket, { TicketButton } from '../components/trading/OrderTicket';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { stockPath } from '../utils/stocks';
import { useReconnect, useTopic } from '../hooks/useStream';
import {
  formatCurrency,
  formatQuantity,
  formatNoteDate,
  formatClock,
  marketPhase,
} from '../utils/formatters';

/**
 * Practice → Book: how the practice money is doing -- one net-of-charges
 * figure for the chosen period with its curve, what is open, and the fills.
 *
 * The curve is built from closed round trips rather than a stored equity
 * series — the ledger records trades, and inventing a smoother series than
 * the one the trades support would be a nicer chart of a worse truth.
 */

const CurveTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="sheet px-3 py-2 text-xs">
      <p className="doc-meta">{point.label}</p>
      <p className="figure-md mt-1">{formatCurrency(point.net)}</p>
    </div>
  );
};

const CLOSED_LIMIT = 1000;
const PERIODS = [['today', 'Today'], ['month', 'Month'], ['all', 'All time']];

const Portfolio = () => {
  const [params, setParams] = useSearchParams();
  const period = PERIODS.some(([id]) => id === params.get('period')) ? params.get('period') : 'all';
  const [openRow, setOpenRow] = useState(null);
  const [positions, setPositions] = useState({});
  const [trades, setTrades] = useState([]);
  const [fills, setFills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [ticket, setTicket] = useState(null);
  const [allFills, setAllFills] = useState(false);
  const [openOrders, setOpenOrders] = useState([]);

  const load = () => {
    Promise.all([
      api.get(endpoints.trading.positions('paper')),
      // The API's maximum; past it All time says it covers only the newest (CLOSED_LIMIT).
      api.get(endpoints.trading.trades('CLOSED', 'paper'), { params: { limit: CLOSED_LIMIT } }),
    ])
      .then(([positionsRes, tradesRes]) => {
        setPositions(positionsRes.data);
        setTrades(tradesRes.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the book'))
      .finally(() => setLoading(false));
    // Executions fail on their own: a slow fills query must not blank the book.
    api
      .get(endpoints.trading.fills('paper'))
      .then((res) => setFills(res.data))
      .catch(() => {});
  };

  useEffect(load, []);

  const loadOpenOrders = () =>
    api
      .get(endpoints.orders.paper)
      .then((res) => setOpenOrders(res.data))
      .catch(() => {});

  useEffect(() => {
    loadOpenOrders();
    const timer = setInterval(() => !document.hidden && loadOpenOrders(), 60000); // not in a hidden tab
    return () => clearInterval(timer);
  }, []);

  const cancelOpenOrder = (id) =>
    api.post(endpoints.orders.cancelPaper(id)).finally(loadOpenOrders);
  useTopic('positions', (message) => setPositions(paperPositions(message.data)));
  useTopic('trades', load);
  useReconnect(() => {
    load();
    loadOpenOrders();
  });

  const summary = useMemo(() => periodSummary(trades, period), [trades, period]);
  const curve = useMemo(
    () => summary.curve.map((point) => ({ ...point, label: formatNoteDate(new Date(point.t)) })),
    [summary]
  );

  const open = Object.values(positions);
  const sortedFills = [...fills].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 25);
  // Latest 10 by default: the full list was most of the page on a phone.
  const recentFills = allFills ? sortedFills : sortedFills.slice(0, 10);
  const closedMarket = marketPhase() !== 'open';
  const unrealisedTotal = open.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);

  if (loading) {
    return (
      <Layout>
        <PaperShell>
          <Sheet title="Holdings">
            <Ruling rows={6} />
          </Sheet>
        </PaperShell>
      </Layout>
    );
  }

  return (
    <Layout>
      <PaperShell>
        {error && (
          <Sheet title="Holdings">
            <Empty title="Could not load the book" detail={error} />
          </Sheet>
        )}

        <Sheet
          title="Practice money"
          meta={summary.trades ? `${summary.trades} closed · ${Math.round(summary.winRate * 100)}% won` : 'Net of charges'}
        >
          <div className="grid grid-cols-3 border border-[var(--rule-strong)] mb-3" role="tablist" aria-label="Period">
            {PERIODS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={period === id}
                      onClick={() => setParams(id === 'all' ? {} : { period: id }, { replace: true })}
                      className={cn('min-h-11 field-label touch-manipulation',
                        period === id ? 'bg-[var(--ink)] text-[var(--paper)]' : 'text-[var(--ink-soft)] hover:text-[var(--ink)]')}>
                {label}
              </button>
            ))}
          </div>
          {period === 'all' && trades.length >= CLOSED_LIMIT && (
            <p className="doc-meta normal-case pb-2">Covers the newest {CLOSED_LIMIT} closed trades.</p>
          )}
          {summary.trades === 0 ? (
            <p className="doc-meta normal-case py-2">No closed trades this period.</p>
          ) : (
            <>
              <NetLine label={`${PERIODS.find(([id]) => id === period)[1]}, net of charges`}>
                <Money value={summary.net} size="lg" />
              </NetLine>
              {curve.length > 1 && (
                <div className="h-40 -mx-2 mt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={curve} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                      <defs>
                        <linearGradient id="curve-ink" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--stamp)" stopOpacity={0.22} />
                          <stop offset="100%" stopColor="var(--stamp)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="label" hide />
                      <YAxis width={54} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} axisLine={false} tickLine={false}
                             tickFormatter={(value) => formatQuantity(value)} />
                      <ReferenceLine y={0} stroke="var(--rule-strong)" strokeWidth={1} />
                      <Tooltip content={<CurveTooltip />} cursor={{ stroke: 'var(--rule-strong)' }} />
                      <Area type="monotone" dataKey="net" stroke="var(--stamp)" strokeWidth={1.5} fill="url(#curve-ink)" isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          )}
        </Sheet>

        <Sheet title="Open positions" meta={`${open.length} scrip`}>
          {open.length === 0 ? (
            <Empty
              title="Nothing open"
              detail="Approved proposals and intraday fills appear here while they are held."
            />
          ) : (
            <>
              {/* One compact row each; a tap reveals Sell / Add, which are rarely used. */}
              <ul className="divide-y divide-[var(--rule)]">
                {open.map((position) => (
                  <li key={position.symbol} className="py-2">
                    <button type="button" onClick={() => setOpenRow((s) => (s === position.symbol ? null : position.symbol))}
                            aria-expanded={openRow === position.symbol}
                            className="w-full flex items-baseline gap-3 text-left min-h-11">
                      <span className="min-w-0 flex-1">
                        <Scrip symbol={position.symbol} />
                        <span className="block doc-meta normal-case">
                          {formatQuantity(position.quantity)} @ {formatCurrency(position.avg_price)} · {formatCurrency(position.quantity * position.avg_price)}
                        </span>
                      </span>
                      <span className="text-right">
                        <Money value={position.unrealized_pnl} />
                        {closedMarket && <span className="block doc-meta normal-case">at last close</span>}
                      </span>
                    </button>
                    {openRow === position.symbol && (
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <TicketButton label="Sell" tone="loss" onClick={() => setTicket({ symbol: position.symbol, side: 'SELL' })} />
                        <TicketButton label="Add" onClick={() => setTicket({ symbol: position.symbol })} />
                        <Link to={stockPath(position.symbol)} className="field-label text-[var(--stamp)] hover:underline ml-auto">Stock ›</Link>
                      </div>
                    )}
                  </li>
                ))}
              </ul>

              <NetLine label={closedMarket ? 'Unrealised, at last close' : 'Unrealised, marked now'}>
                <Money value={unrealisedTotal} size="lg" />
              </NetLine>
            </>
          )}
        </Sheet>

        {openOrders.length > 0 && (
          <Sheet title="Open orders" meta={`${openOrders.length}`}>
            <Statement
              columns={[
                { key: 'scrip', label: 'Scrip' },
                { key: 'side', label: 'Side' },
                { key: 'qty', label: 'Qty', align: 'right' },
                { key: 'limit', label: 'Limit', align: 'right' },
                { key: 'placed', label: 'Placed', align: 'right' },
                { key: 'cancel', label: '', align: 'right' },
              ]}
            >
              {openOrders.map((order) => (
                <Row key={order.id}>
                  <Cell>
                    <Scrip symbol={order.symbol} />
                  </Cell>
                  <Cell>{order.side === 'BUY' ? 'Buy' : 'Sell'}</Cell>
                  <Cell align="right" mono>
                    {formatQuantity(order.quantity)}
                  </Cell>
                  <Cell align="right" mono>
                    {formatCurrency(order.limit_price)}
                  </Cell>
                  <Cell align="right" mono>
                    {new Date(order.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })}
                  </Cell>
                  <Cell align="right">
                    <TicketButton label="Cancel" tone="loss" onClick={() => cancelOpenOrder(order.id)} />
                  </Cell>
                </Row>
              ))}
            </Statement>
          </Sheet>
        )}

        <Sheet title="Executions" meta={fills.length > sortedFills.length ? `Latest ${sortedFills.length} of ${fills.length}` : `${fills.length} fills`}>
          {recentFills.length === 0 ? (
            <Empty title="No executions yet" detail="Fills appear here as orders are filled." />
          ) : (
            <Statement
              inline
              columns={[
                { key: 'scrip', label: 'Scrip' },
                { key: 'time', label: 'Time' },
                { key: 'side', label: 'Side' },
                { key: 'qty', label: 'Qty', align: 'right' },
                { key: 'price', label: 'Price', align: 'right' },
                { key: 'costs', label: 'Charges', align: 'right' },
              ]}
            >
              {recentFills.map((fill) => (
                <Row key={`${fill.order_id}-${fill.timestamp}`}>
                  <Cell>
                    <Scrip symbol={fill.symbol} />
                    {/* Phone: side and time ride along with the scrip on one line. */}
                    <span className={cn('sm:hidden ml-2 text-xs figure-md', fill.side === 'BUY' ? 'text-up' : 'text-down')}>
                      {fill.side}
                    </span>
                    <span className="sm:hidden ml-2 doc-meta">{formatClock(fill.timestamp)}</span>
                  </Cell>
                  <Cell className="doc-meta normal-case phone-hide">{formatClock(fill.timestamp)}</Cell>
                  <Cell className="phone-hide">
                    <Badge variant={fill.side === 'BUY' ? 'success' : 'destructive'}>
                      {fill.side}
                    </Badge>
                  </Cell>
                  <Cell align="right" mono>
                    {formatQuantity(fill.quantity)}
                  </Cell>
                  <Cell align="right" mono>
                    {formatCurrency(fill.price)}
                  </Cell>
                  <Cell align="right" mono className="text-[var(--ink-faint)] phone-hide">
                    {formatCurrency(fill.costs)}
                  </Cell>
                </Row>
              ))}
            </Statement>
          )}
                  {sortedFills.length > 10 && (
            <button
              type="button"
              onClick={() => setAllFills((value) => !value)}
              aria-expanded={allFills}
              className="mt-2 field-label text-[var(--stamp)] hover:underline min-h-11 sm:min-h-0"
            >
              {allFills ? 'Show latest 10' : `Show latest ${sortedFills.length}`}
            </button>
          )}
        </Sheet>

      </PaperShell>
      {ticket && (
        <OrderTicket
          {...ticket}
          venue="paper"
          onClose={() => setTicket(null)}
          onDone={() => {
            load();
            loadOpenOrders();
          }}
        />
      )}
    </Layout>
  );
};

export default Portfolio;
