import React, { useEffect, useMemo, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import { formatCurrency } from '../../utils/formatters';
import {
  RANGES, newsMarkers, prevClose, rangeChange, toBars, tradeMarkers, visibleRanges,
} from '../../utils/stock';
import { usePrivacy } from '../../hooks/usePrivacy';
import { toneText } from '../ui/tone';
import PriceCanvas from './PriceCanvas';
import NewsStrip from './NewsStrip';

const INTRADAY_POLL_MS = 60_000;
const IST = 'Asia/Kolkata';

// A daily bar is a calendar day (no zone shift); an intraday bar is a moment, read in IST.
const when = (date, withDay) => (String(date).length === 10
  ? new Date(date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  : new Date(date).toLocaleString('en-IN', {
    ...(withDay ? { weekday: 'short', day: 'numeric', month: 'short' } : {}), hour: 'numeric', minute: '2-digit', timeZone: IST,
  }));
const compact = (v) => (v == null ? '—' : Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(v));

const Chip = ({ on, disabled, onClick, children, label }) => (
  <button type="button" aria-pressed={on} aria-label={label} disabled={disabled} onClick={onClick}
    className={`min-h-11 min-w-11 px-3 rounded-full text-[13px] font-medium tabular-nums transition-colors disabled:opacity-40 ${
      on ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'
    }`}>
    {children}
  </button>
);
const Group = ({ label, children }) => (
  <div role="group" aria-label={label} className="inline-flex items-center rounded-full bg-[var(--surface-2)] p-1">{children}</div>
);

/**
 * Price chart (lightweight-charts via PriceCanvas): candles or area, volume, a readout that follows the
 * crosshair, ranges 1D/1W (intraday feed, `days=1|5`) and 1M-5Y (daily bars). `closes` is any daily feed
 * utils/stock.js::toBars reads (candles, OHLCV bars, or close-only); `trades` your fills as B/S arrows;
 * `thesis` stop/target lines; news days as dots that open a NewsStrip. An index passes `currency="pts"`,
 * its own `intradayUrl` and `newsUrl={null}`.
 */
const TradingChart = ({ closes, trades, thesis, symbol, currency = 'INR', initialRange = '1D', intradayUrl, newsUrl }) => {
  const fmt = (v) => (currency === 'pts' ? Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : formatCurrency(v, currency));
  const newsFrom = newsUrl === undefined ? (symbol && endpoints.newsHistory(symbol)) : newsUrl;
  const dayFrom = intradayUrl || (symbol && endpoints.intraday(symbol));
  const hidden = usePrivacy();

  const daily = useMemo(() => toBars(closes, { daily: true }), [closes]);
  const chips = visibleRanges(daily.bars.length);
  const [picked, setRange] = useState(initialRange);
  const range = chips.includes(picked) ? picked : chips.at(-1);
  const spec = RANGES.find(([k]) => k === range)[1];
  const days = typeof spec === 'object' ? spec.days : null;

  const [loaded, setLoaded] = useState(null); // {symbol, days, rows}: another stock's or range's rows never show
  const [mode, setMode] = useState('candle');
  const [showNews, setShowNews] = useState(true);
  const [news, setNews] = useState(null); // {symbol, items}
  const [pickedDay, setPickedDay] = useState(null); // {symbol, date}
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!symbol || !newsFrom) return undefined; // no markers: `news` stays null
    let gone = false;
    api.get(newsFrom)
      .then((res) => !gone && setNews({ symbol, items: res.data.items || [] }))
      .catch(() => !gone && setNews({ symbol, items: [] })); // markers are extra: the chart works without them
    return () => { gone = true; };
  }, [symbol, newsFrom]);

  useEffect(() => {
    if (!days || !symbol || !dayFrom) return undefined;
    let gone = false;
    const load = () => api.get(dayFrom, { params: { days } })
      .then((res) => !gone && setLoaded({ symbol, days, rows: res.data }))
      .catch(() => !gone && setLoaded((p) => (p?.symbol === symbol && p.days === days ? p : { symbol, days, rows: [] }))); // a failed poll keeps what is shown
    load();
    const timer = setInterval(load, INTRADAY_POLL_MS);
    return () => { gone = true; clearInterval(timer); };
  }, [days, symbol, dayFrom]);

  const intra = useMemo(
    () => (loaded?.symbol === symbol && loaded.days === days ? toBars(loaded.rows, { daily: false }) : null),
    [loaded, symbol, days],
  );
  const shown = useMemo(
    () => (days ? intra || { bars: [], ohlc: false } : { bars: daily.bars.slice(-spec), ohlc: daily.ohlc }),
    [days, intra, daily, spec],
  );
  const bars = shown.bars;
  const view = shown.ohlc ? mode : 'area';

  const tradeDots = useMemo(() => {
    if (days) return [];
    const have = new Set(bars.map((b) => b.date));
    return tradeMarkers(daily.bars, trades).filter((m) => have.has(m.date)).map((m) => ({ date: m.date, kind: m.side === 'SELL' ? 'sell' : 'buy' }));
  }, [days, bars, daily, trades]);
  const allNews = useMemo(() => (days || news?.symbol !== symbol ? [] : newsMarkers(bars, news.items)), [days, news, symbol, bars]);
  const newsDots = useMemo(() => (showNews ? allNews : []), [showNews, allNews]); // stable: markers feed the canvas
  const markers = useMemo(
    () => [...tradeDots, ...newsDots.map((m) => ({ date: m.date, kind: 'news', direction: m.direction, impact: m.impact }))],
    [tradeDots, newsDots],
  );
  const pickedMark = pickedDay?.symbol === symbol ? newsDots.find((m) => m.date === pickedDay.date) : null;
  const pick = (date) => setPickedDay((p) => (p?.symbol === symbol && p.date === date ? null : { symbol, date }));

  const lines = useMemo(() => (days ? [] : [
    thesis?.target != null && { price: thesis.target, tone: 'gain', title: 'Target', name: 'Target', amount: fmt(thesis.target) },
    thesis?.stop != null && { price: thesis.stop, tone: 'loss', title: 'Stop', name: 'Stop', amount: fmt(thesis.stop) },
  ].filter(Boolean)), [days, thesis?.target, thesis?.stop, currency]); // eslint-disable-line react-hooks/exhaustive-deps
  const baseline = days === 1 && bars.length ? prevClose(daily.bars, String(bars[0].date).slice(0, 10)) : null;

  // Readout: the hovered bar, else the latest; change is from the range's first bar (1D: the previous close).
  const last = bars.at(-1);
  const focus = hover || last;
  const from = baseline ?? bars[0]?.close;
  const change = focus && from != null ? { abs: focus.close - from, pct: from ? ((focus.close - from) / from) * 100 : 0 } : rangeChange(bars);
  const tone = !change || change.abs === 0 ? 'neutral' : change.abs > 0 ? 'gain' : 'loss';
  const sign = change?.abs > 0 ? '+' : '';
  const span = range === '1D' ? 'today' : `in ${range}`;

  return (
    <div>
      <div className="min-h-[60px]" aria-live="off">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[24px] font-semibold tabular-nums tracking-tight">{focus ? fmt(focus.close) : '—'}</span>
          {change && (
            <span className={`text-[14px] font-medium tabular-nums ${toneText(tone)}`}>
              {sign}{fmt(change.abs)} ({sign}{change.pct.toFixed(2)}%)
            </span>
          )}
          <span className="text-[13px] text-[var(--text-muted)]">{hover ? when(hover.date, range === '1W') : span}</span>
        </div>
        <div className="text-[12px] text-[var(--text-muted)] tabular-nums h-5">
          {hover && shown.ohlc && <>O {fmt(hover.open)} · H {fmt(hover.high)} · L {fmt(hover.low)}{hover.volume ? ` · Vol ${compact(hover.volume)}` : ''}</>}
        </div>
      </div>

      {bars.length < 2 ? (
        <div className="h-[320px] sm:h-[420px] flex items-center justify-center text-[14px] text-[var(--text-muted)]">
          {days && !intra ? 'Loading…' : 'No price history for this range.'}
        </div>
      ) : (
        <div className="h-[320px] sm:h-[420px] -mx-1" role="img"
          aria-label={`Price, last ${fmt(last.close)}, ${change ? `${sign}${change.pct.toFixed(2)}%` : ''} ${span}; ${tradeDots.length} of your trades and ${newsDots.length} news days marked`}>
          <PriceCanvas bars={bars} mode={view} markers={markers} priceLines={lines} baseline={baseline} hidePrices={hidden}
            onCrosshair={setHover} onPickDate={pick} />
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <Group label="Chart range">
          {chips.map((k) => <Chip key={k} on={range === k} onClick={() => { setRange(k); setHover(null); }}>{k}</Chip>)}
        </Group>
        <div className="flex items-center gap-2">
          <Group label="Chart style">
            <Chip on={view === 'candle'} disabled={!shown.ohlc} onClick={() => setMode('candle')} label="Candles">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="currentColor"><rect x="2" y="4" width="3" height="6" /><rect x="3" y="1" width="1" height="12" /><rect x="9" y="3" width="3" height="5" /><rect x="10" y="1" width="1" height="11" /></svg>
            </Chip>
            <Chip on={view === 'area'} onClick={() => setMode('area')} label="Area">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M1 11 L5 6 L8 8 L13 2" /></svg>
            </Chip>
          </Group>
          {!days && allNews.length > 0 && (
            <Group label="News on chart">
              <Chip on={showNews} onClick={() => setShowNews((v) => !v)}>
                News <span className="text-[12px] opacity-70">{allNews.length}</span>
              </Chip>
            </Group>
          )}
        </div>
      </div>

      {pickedMark && <NewsStrip mark={pickedMark} onClose={() => setPickedDay(null)} />}
      {!pickedMark && newsDots.length > 0 && (
        // Canvas dots are not focusable: the same news days as buttons, newest first.
        <ul aria-label="News days" className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
          {[...newsDots].reverse().map((m) => (
            <li key={m.date} className="shrink-0">
              <button type="button" onClick={() => pick(m.date)}
                aria-label={`${m.count} news ${m.count === 1 ? 'item' : 'items'} on ${when(m.date)}: ${m.items[0].title}`}
                className="min-h-11 px-3 rounded-full bg-[var(--surface-2)] text-[12px] font-medium tabular-nums inline-flex items-center gap-1.5 text-[var(--text-muted)] hover:text-[var(--text)]">
                <span aria-hidden="true" className={m.direction > 0 ? 'text-[var(--gain)]' : m.direction < 0 ? 'text-[var(--loss)]' : ''}>
                  {m.direction > 0 ? '▲' : m.direction < 0 ? '▼' : '◆'}
                </span>
                {when(m.date)}{m.count > 1 ? ` · ${m.count}` : ''}
              </button>
            </li>
          ))}
        </ul>
      )}

      {lines.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-[var(--text-muted)]">
          {lines.map((l) => (
            <li key={l.name} className="inline-flex items-center gap-1.5">
              <svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke={`var(--${l.tone})`} strokeWidth="2" strokeDasharray="5 4" /></svg>
              {l.name} <span className="private">{l.amount}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default TradingChart;
