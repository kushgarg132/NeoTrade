import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import {
  formatCurrency,
  formatQuantity,
  formatNoteDate,
  formatPercent,
  formatClock,
} from '../utils/formatters';

/**
 * The holdings book: what is open, marked live, and the running result of
 * everything already closed.
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
      <p className="figure-md mt-1">{formatCurrency(point.cumulative)}</p>
    </div>
  );
};

const Portfolio = () => {
  const navigate = useNavigate();
  const [positions, setPositions] = useState({});
  const [trades, setTrades] = useState([]);
  const [pnl, setPnl] = useState(null);
  const [fills, setFills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    Promise.all([
      api.get(endpoints.trading.positions('paper')),
      api.get(endpoints.trading.trades('CLOSED', 'paper')),
      api.get(endpoints.analytics.pnl('paper')),
      api.get(endpoints.trading.fills('paper')),
    ])
      .then(([positionsRes, tradesRes, pnlRes, fillsRes]) => {
        setFills(fillsRes.data);
        setPositions(positionsRes.data);
        setTrades(tradesRes.data);
        setPnl(pnlRes.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the book'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);
  useTopic('positions', (message) => setPositions(paperPositions(message.data)));
  useTopic('pnl', (message) => message.data?.paper && setPnl(message.data.paper));
  useTopic('trades', load);

  const curve = useMemo(() => {
    const closed = [...trades]
      .filter((trade) => trade.exit_at)
      .sort((a, b) => new Date(a.exit_at) - new Date(b.exit_at));
    return closed.reduce((points, trade) => {
      const previous = points.length ? points[points.length - 1].cumulative : 0;
      points.push({
        label: `${formatNoteDate(new Date(trade.exit_at))} · ${trade.symbol}`,
        cumulative: previous + (trade.realized_pnl || 0),
      });
      return points;
    }, []);
  }, [trades]);

  const open = Object.values(positions);
  const recentFills = [...fills].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 25);
  const realisedTotal = curve.length ? curve[curve.length - 1].cumulative : 0;

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

        <Sheet title="Realised result" meta={`${curve.length} closed`}>
          {curve.length === 0 ? (
            <Empty
              title="No closed trades yet"
              detail="The curve is drawn from completed round trips, so it starts once a position returns to flat."
            />
          ) : (
            <>
              <div className="h-48 -mx-2">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={curve} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                    <defs>
                      <linearGradient id="curve-ink" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--stamp)" stopOpacity={0.22} />
                        <stop offset="100%" stopColor="var(--stamp)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="label" hide />
                    <YAxis
                      width={54}
                      tick={{ fontSize: 10, fill: 'var(--ink-faint)' }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(value) => formatQuantity(value)}
                    />
                    <ReferenceLine y={0} stroke="var(--rule-strong)" strokeWidth={1} />
                    <Tooltip content={<CurveTooltip />} cursor={{ stroke: 'var(--rule-strong)' }} />
                    <Area
                      type="monotone"
                      dataKey="cumulative"
                      stroke="var(--stamp)"
                      strokeWidth={1.5}
                      fill="url(#curve-ink)"
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <NetLine label="Realised, all time">
                <Money value={realisedTotal} size="lg" />
              </NetLine>
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
              <Statement
                columns={[
                  { key: 'scrip', label: 'Scrip' },
                  { key: 'qty', label: 'Qty', align: 'right' },
                  { key: 'avg', label: 'Avg cost', align: 'right' },
                  { key: 'value', label: 'Value', align: 'right' },
                  { key: 'unreal', label: 'Unrealised', align: 'right' },
                ]}
              >
                {open.map((position) => (
                  <Row
                    key={position.symbol}
                    className="cursor-pointer hover:bg-[var(--paper-sunk)]"
                    onClick={() => navigate('/', { state: { symbol: position.symbol } })}
                  >
                    <Cell>
                      <Scrip symbol={position.symbol} />
                    </Cell>
                    <Cell align="right" mono>
                      {formatQuantity(position.quantity)}
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(position.avg_price)}
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(position.quantity * position.avg_price)}
                    </Cell>
                    <Cell align="right">
                      <Money value={position.unrealized_pnl} />
                    </Cell>
                  </Row>
                ))}
              </Statement>

              {pnl && (
                <NetLine label="Marked to market">
                  <Money value={pnl.today.unrealized} size="lg" />
                </NetLine>
              )}
            </>
          )}
        </Sheet>

        <Sheet title="Executions" meta={`${fills.length} fills`}>
          {recentFills.length === 0 ? (
            <Empty title="No executions yet" detail="Fills appear here as orders are filled." />
          ) : (
            <Statement
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
                  </Cell>
                  <Cell className="doc-meta normal-case">{formatClock(fill.timestamp)}</Cell>
                  <Cell>
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
                  <Cell align="right" mono className="text-[var(--ink-faint)]">
                    {formatCurrency(fill.costs)}
                  </Cell>
                </Row>
              ))}
            </Statement>
          )}
        </Sheet>

        {pnl && pnl.month.trades > 0 && (
          <Sheet title="Month to date">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <p className="field-label mb-1">Realised</p>
                <Money value={pnl.month.realized} />
              </div>
              <div>
                <p className="field-label mb-1">Strike rate</p>
                <span className="figure-md text-base">
                  {formatPercent(pnl.month.win_rate * 100)}
                </span>
              </div>
              <div>
                <p className="field-label mb-1">Best</p>
                <Money value={pnl.month.best} />
              </div>
              <div>
                <p className="field-label mb-1">Worst</p>
                <Money value={pnl.month.worst} />
              </div>
            </div>
          </Sheet>
        )}
      </PaperShell>
    </Layout>
  );
};

export default Portfolio;
