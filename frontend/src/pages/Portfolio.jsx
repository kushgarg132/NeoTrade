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
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import {
  formatCurrency,
  formatQuantity,
  formatNoteDate,
  formatPercent,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    Promise.all([
      api.get(endpoints.trading.positions),
      api.get(endpoints.trading.trades('CLOSED')),
      api.get(endpoints.analytics.pnl),
    ])
      .then(([positionsRes, tradesRes, pnlRes]) => {
        setPositions(positionsRes.data);
        setTrades(tradesRes.data);
        setPnl(pnlRes.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the book'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);
  useTopic('positions', (message) => setPositions(message.data));
  useTopic('pnl', (message) => setPnl(message.data));
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
  const realisedTotal = curve.length ? curve[curve.length - 1].cumulative : 0;

  if (loading) {
    return (
      <Layout>
        <Sheet title="Holdings">
          <Ruling rows={6} />
        </Sheet>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4">
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
      </div>
    </Layout>
  );
};

export default Portfolio;
