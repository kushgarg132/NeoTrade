import React, { useEffect, useMemo, useState } from 'react';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceDot, ReferenceLine } from 'recharts';
import api, { endpoints } from '../../utils/api';
import { formatClock, formatCurrency } from '../../utils/formatters';
import { tradeMarkers } from '../../utils/stock';
import { AXIS, GRID, TOOLTIP_STYLE } from '../ui/chartTheme';

const INTRADAY_POLL_MS = 60_000;
const RANGES = [['1D', 1], ['1M', 22], ['1Y', 252], ['5Y', 1260]]; // trading days; 1D is the intraday feed

const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });

// Buys are filled circles, sells hollow squares: identity is never colour alone.
const Buy = ({ cx, cy }) => <circle cx={cx} cy={cy} r={5} fill="var(--gain)" stroke="var(--surface)" strokeWidth={2} />;
const Sell = ({ cx, cy }) => <rect x={cx - 4.5} y={cy - 4.5} width={9} height={9} fill="var(--surface)" stroke="var(--loss)" strokeWidth={2} />;

/**
 * Price chart with range chips. `closes`: [{date:'YYYY-MM-DD', close}] daily series; `trades` your fills;
 * `thesis` draws target / stop lines. 1D swaps in the latest session's 5-minute candles.
 */
const TradingChart = ({ closes, trades, thesis, symbol, currency = 'INR' }) => {
  const [range, setRange] = useState('1Y');
  const [loaded, setLoaded] = useState(null); // keyed by symbol so another stock's candles never show
  const isDay = range === '1D';
  const intraday = loaded?.symbol === symbol ? loaded.rows : null;

  useEffect(() => {
    if (!isDay || !symbol) return undefined;
    let gone = false;
    const load = () =>
      api.get(endpoints.intraday(symbol))
        .then((res) => !gone && setLoaded({ symbol, rows: res.data }))
        .catch(() => !gone && setLoaded({ symbol, rows: [] }));
    load();
    const timer = setInterval(load, INTRADAY_POLL_MS);
    return () => {
      gone = true;
      clearInterval(timer);
    };
  }, [isDay, symbol]);

  const data = useMemo(() => {
    if (isDay) return (intraday || []).map((r) => ({ date: formatClock(r.timestamp), close: Number(r.close) }));
    return (closes || []).slice(-RANGES.find(([k]) => k === range)[1]);
  }, [closes, range, isDay, intraday]);

  const dots = useMemo(() => {
    if (isDay) return [];
    const have = new Set(data.map((d) => d.date));
    return tradeMarkers(closes, trades).filter((m) => have.has(m.date));
  }, [closes, trades, data, isDay]);

  const lines = [
    thesis?.target != null && { y: thesis.target, color: 'var(--gain)', name: 'Target', amount: formatCurrency(thesis.target, currency) },
    thesis?.stop != null && { y: thesis.stop, color: 'var(--loss)', name: 'Stop', amount: formatCurrency(thesis.stop, currency) },
  ].filter(Boolean);
  const first = data[0]?.close;
  const last = data.at(-1)?.close;
  const up = last == null || first == null || last >= first;

  return (
    <div>
      <div role="group" aria-label="Chart range" className="flex gap-1 mb-3">
        {RANGES.map(([k]) => (
          <button
            key={k}
            type="button"
            onClick={() => setRange(k)}
            aria-pressed={range === k}
            className={`min-h-11 flex-1 rounded-[12px] text-[14px] font-medium ${
              range === k ? 'bg-[var(--accent)] text-[var(--surface)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]'
            }`}
          >
            {k}
          </button>
        ))}
      </div>
      {data.length < 2 ? (
        <div className="h-56 flex items-center justify-center text-[14px] text-[var(--text-muted)]">
          {isDay && intraday === null ? 'Loading…' : 'No price history for this range.'}
        </div>
      ) : (
        <div className="h-56 sm:h-72" role="img" aria-label={`Price, last ${formatCurrency(last, currency)}, ${dots.length} of your trades marked`}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="date" tickFormatter={isDay ? undefined : short} {...AXIS} minTickGap={48} />
              <YAxis {...AXIS} width={52} axisLine={false} domain={['auto', 'auto']} tickFormatter={(v) => Math.round(v).toLocaleString('en-IN')} />
              <Tooltip
                formatter={(v) => [formatCurrency(v, currency), 'Price']}
                labelFormatter={isDay ? undefined : short}
                contentStyle={TOOLTIP_STYLE}
              />
              <Line type="monotone" dataKey="close" stroke={up ? 'var(--gain)' : 'var(--loss)'} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
              {!isDay && lines.map((l) => (
                <ReferenceLine key={l.name} y={l.y} stroke={l.color} strokeWidth={1.5} strokeDasharray="5 4" ifOverflow="extendDomain" />
              ))}
              {dots.map((t, i) => (
                <ReferenceDot key={i} x={t.date} y={t.price} shape={t.side === 'SELL' ? Sell : Buy} ifOverflow="extendDomain" />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {!isDay && (dots.length > 0 || lines.length > 0) && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-[var(--text-muted)]">
          {dots.some((d) => d.side !== 'SELL') && <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Buy cx={5} cy={5} /></svg>Your buys</li>}
          {dots.some((d) => d.side === 'SELL') && <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Sell cx={5} cy={5} /></svg>Your sells</li>}
          {lines.map((l) => (
            <li key={l.name} className="inline-flex items-center gap-1.5">
              <svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke={l.color} strokeWidth="2" strokeDasharray="5 4" /></svg>
              {l.name} <span className="private">{l.amount}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default TradingChart;
