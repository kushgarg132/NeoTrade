import React, { useEffect, useMemo, useState } from 'react';
import { ImpactChips, NewsLink } from '../common/NewsImpacts';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceDot, ReferenceLine } from 'recharts';
import api, { endpoints } from '../../utils/api';
import { formatClock, formatCurrency, formatDateTime } from '../../utils/formatters';
import { newsMarkers, tradeMarkers } from '../../utils/stock';
import { AXIS, GRID, TOOLTIP_STYLE } from '../ui/chartTheme';

const INTRADAY_POLL_MS = 60_000;
const RANGES = [['1D', 1], ['1M', 22], ['1Y', 252], ['5Y', 1260]]; // trading days; 1D is the intraday feed

const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });

// Buys are filled circles, sells hollow squares: identity is never colour alone.
const Buy = ({ cx, cy }) => <circle cx={cx} cy={cy} r={5} fill="var(--gain)" stroke="var(--surface)" strokeWidth={2} />;
const Sell = ({ cx, cy }) => <rect x={cx - 4.5} y={cy - 4.5} width={9} height={9} fill="var(--surface)" stroke="var(--loss)" strokeWidth={2} />;

// News: a triangle pointing the way the news leans (diamond = mixed), sized by impact, drawn above the price.
const NEWS_LIFT = 14;
const newsColor = (d) => (d > 0 ? 'var(--gain)' : d < 0 ? 'var(--loss)' : 'var(--text-muted)');
const NewsGlyph = ({ cx, cy, direction, impact = 6 }) => {
  const s = 3 + impact * 0.5;
  const d = direction > 0 ? `M${cx},${cy - s}L${cx + s},${cy + s * 0.8}L${cx - s},${cy + s * 0.8}Z`
    : direction < 0 ? `M${cx},${cy + s}L${cx + s},${cy - s * 0.8}L${cx - s},${cy - s * 0.8}Z`
      : `M${cx},${cy - s}L${cx + s},${cy}L${cx},${cy + s}L${cx - s},${cy}Z`;
  return <path d={d} fill={newsColor(direction)} stroke="var(--surface)" strokeWidth={1.5} />;
};
const NewsMark = ({ cx, cy, m, onPick }) => {
  if (cx == null || cy == null) return null;
  const y = cy - NEWS_LIFT;
  const label = `${m.count} news ${m.count === 1 ? 'item' : 'items'} on ${short(m.date)}: ${m.items[0].title}`;
  return (
    <g role="button" tabIndex={0} aria-label={label} style={{ cursor: 'pointer' }} onClick={() => onPick(m.date)}
       onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onPick(m.date)}>
      <title>{m.items.map((i) => i.title).join('\n')}</title>
      <circle cx={cx} cy={y} r={14} fill="transparent" />
      <NewsGlyph cx={cx} cy={y} direction={m.direction} impact={m.impact} />
      {m.count > 1 && <text x={cx + 8} y={y - 6} fontSize={12} fontWeight={600} fill="var(--text)">{m.count}</text>}
    </g>
  );
};

/**
 * Price chart with range chips. `closes`: [{date:'YYYY-MM-DD', close}] daily series; `trades` your fills;
 * `thesis` draws target / stop lines. 1D swaps in the latest session's 5-minute candles. `initialRange`
 * defaults to today (1D); a trade page passes a longer one so its fills are on screen.
 */
const TradingChart = ({ closes, trades, thesis, symbol, currency = 'INR', initialRange = '1D' }) => {
  const [range, setRange] = useState(initialRange);
  const [loaded, setLoaded] = useState(null); // keyed by symbol so another stock's candles never show
  const isDay = range === '1D';
  const intraday = loaded?.symbol === symbol ? loaded.rows : null;
  const [showNews, setShowNews] = useState(true);
  const [news, setNews] = useState(null); // {symbol, items}, keyed like `loaded`
  const [picked, setPicked] = useState(null); // {symbol, date} of the tapped news marker

  useEffect(() => {
    if (!symbol) return undefined;
    let gone = false;
    api.get(endpoints.newsHistory(symbol))
      .then((res) => !gone && setNews({ symbol, items: res.data.items || [] }))
      .catch(() => !gone && setNews({ symbol, items: [] })); // markers are extra: the chart works without them
    return () => { gone = true; };
  }, [symbol]);

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

  // Only the visible range, at most NEWS_MARKER_CAP days (newsMarkers keeps the most impactful).
  const allNews = useMemo(
    () => (isDay || news?.symbol !== symbol ? [] : newsMarkers(data, news.items)),
    [data, news, symbol, isDay],
  );
  const newsDots = showNews ? allNews : [];
  const pickedMark = picked?.symbol === symbol ? newsDots.find((m) => m.date === picked.date) : null;
  const pick = (date) => setPicked((p) => (p?.symbol === symbol && p.date === date ? null : { symbol, date }));

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
              range === k ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]'
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
        <div className="h-56 sm:h-72" role="img" aria-label={`Price, last ${formatCurrency(last, currency)}, ${dots.length} of your trades and ${newsDots.length} news days marked`}>
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
              {newsDots.map((m) => (
                <ReferenceDot key={`n${m.date}`} x={m.date} y={m.price} ifOverflow="extendDomain"
                  shape={(p) => <NewsMark cx={p.cx} cy={p.cy} m={m} onPick={pick} />} />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {pickedMark && (
        <ul className="mt-2 rounded-[12px] bg-[var(--surface-2)] px-3 py-1" aria-label={`News on ${short(pickedMark.date)}`}>
          {pickedMark.items.map((i) => (
            <li key={i.id ?? i.url ?? i.title} className="flex items-start gap-2 py-2 text-[14px]">
              <svg width="12" height="12" className="mt-1 shrink-0" aria-hidden="true"><NewsGlyph cx={6} cy={6} direction={Math.sign(i.direction || 0)} impact={4} /></svg>
              <span className="min-w-0">
                {i.id || i.url ? <NewsLink id={i.id} url={i.url} className="text-[var(--accent)] underline-offset-2 hover:underline">{i.title}</NewsLink> : i.title}
                <span className="block text-[12px] text-[var(--text-muted)] tabular-nums">
                  {i.direction > 0 ? 'Good' : i.direction < 0 ? 'Bad' : 'Mixed'} news · impact {i.impact}/10 · {formatDateTime(i.published_at)}
                </span>
                <ImpactChips impacts={i.impacts} className="mt-0.5" />
              </span>
            </li>
          ))}
        </ul>
      )}
      {!isDay && allNews.length > 0 && (
        <button type="button" aria-pressed={showNews} onClick={() => setShowNews((v) => !v)}
          className={`mt-2 min-h-11 rounded-[12px] px-3 text-[14px] font-medium inline-flex items-center gap-2 ${
            showNews ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]'
          }`}>
          News
          <span className="tabular-nums text-[12px]">{allNews.length} {allNews.length === 1 ? 'day' : 'days'}</span>
        </button>
      )}
      {!isDay && (dots.length > 0 || lines.length > 0 || newsDots.length > 0) && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-[var(--text-muted)]">
          {dots.some((d) => d.side !== 'SELL') && <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Buy cx={5} cy={5} /></svg>Your buys</li>}
          {dots.some((d) => d.side === 'SELL') && <li className="inline-flex items-center gap-1.5"><svg width="10" height="10" aria-hidden="true"><Sell cx={5} cy={5} /></svg>Your sells</li>}
          {newsDots.length > 0 && (
            <li className="inline-flex items-center gap-1.5">
              <svg width="20" height="10" aria-hidden="true"><NewsGlyph cx={5} cy={5} direction={1} impact={2} /><NewsGlyph cx={15} cy={5} direction={-1} impact={2} /></svg>
              Material news, bigger = more impact; tap for headlines
            </li>
          )}
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
