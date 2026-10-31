import { test } from 'node:test';
import assert from 'node:assert/strict';
import { newsMarkers, positionSummary, tradeMarkers } from './stock.js';

test('positionSummary: held position, percent to fraction, weight of the portfolio', () => {
  const s = positionSummary({ qty: 10, avg_price: 3377, value: 41200, pnl: 7430, pnl_pct: 22, sold: false }, 412000);
  assert.deepEqual(s, { qty: 10, avg: 3377, value: 41200, pnl: 7430, pnlPct: 0.22, weight: 0.1 });
});

test('positionSummary: null when not held or sold; no weight without a portfolio value', () => {
  assert.equal(positionSummary(undefined, 1), null);
  assert.equal(positionSummary({ qty: 0, sold: true }, 1), null);
  assert.equal(positionSummary({ qty: 2, value: 10, pnl_pct: null }, 0).weight, null);
  assert.equal(positionSummary({ qty: 2, value: 10, pnl_pct: null }, 0).pnlPct, null);
});

test('tradeMarkers snaps to the last close on or before, drops earlier ones', () => {
  const closes = [{ date: '2026-01-02', close: 10 }, { date: '2026-01-05', close: 12 }];
  const m = tradeMarkers(closes, [
    { date: '2026-01-04', side: 'BUY', price: 11 },
    { date: '2026-01-05', side: 'SELL' },
    { date: '2025-12-31', side: 'BUY', price: 9 },
  ]);
  assert.deepEqual(m, [
    { date: '2026-01-02', side: 'BUY', price: 11 },
    { date: '2026-01-05', side: 'SELL', price: 12 },
  ]);
  assert.deepEqual(tradeMarkers(null, null), []);
});

test('technical summary counts indicator readings and names the balance', async () => {
  const { techSummary } = await import('./stock.js');
  const s = techSummary({ price: 110, ema_20: 105, sma_50: 100, sma_200: 90, macd: 1, macd_signal: 0.5, rsi: 62 });
  assert.equal(s.bull, 6);
  assert.equal(s.label, 'Mostly bullish');
  const m = techSummary({ price: 100, ema_20: 101, sma_50: 99, rsi: 75 });
  assert.deepEqual([m.bull, m.bear, m.neutral, m.label], [1, 1, 1, 'Mixed']);
  assert.equal(techSummary({}), null);
});

test('newsMarkers: material only, snaps forward to a session, collapses a day, caps by impact', () => {
  const data = [{ date: '2026-10-01', close: 10 }, { date: '2026-10-02', close: 11 }, { date: '2026-10-05', close: 12 }];
  const n = (at, direction, impact, material = true) => ({ published_at: at, direction, impact, material, title: at });
  const out = newsMarkers(data, [
    n('2026-09-30T05:00:00Z', 0.9, 9), // before the series: dropped
    n('2026-10-01T04:00:00Z', 0.8, 7),
    n('2026-10-01T06:00:00Z', -0.7, 9), // same day, outweighs: net bad
    n('2026-10-01T07:00:00Z', 0.9, 2, false), // not material
    n('2026-10-03T20:00:00Z', 0.5, 6), // Sat night UTC = Sun IST -> Monday's session
    n('2026-10-09T05:00:00Z', -0.6, 8), // after the last close -> last close
  ]);
  assert.deepEqual(out.map((m) => [m.date, m.count, m.direction, m.impact, m.price]),
    [['2026-10-01', 2, -1, 9, 10], ['2026-10-05', 2, -1, 8, 12]]);
  assert.equal(out[0].items[0].title, '2026-10-01T06:00:00Z'); // newest first
  assert.deepEqual(newsMarkers(data, [n('2026-10-01T04:00:00Z', 1, 3), n('2026-10-02T04:00:00Z', 1, 8)], 1)
    .map((m) => m.date), ['2026-10-02']);
  assert.deepEqual(newsMarkers([], [n('2026-10-01T04:00:00Z', 1, 8)]), []);
});

// --- price chart helpers (2026-10-31 redesign) ---------------------------------
import { RANGES, chartTime, newsLean, prevClose, rangeChange, toBars, visibleRanges } from './stock.js';

const candle = (d, c, extra = {}) => ({ timestamp: `${d}T00:00:00+05:30`, open: c - 1, high: c + 2, low: c - 2, close: c, volume: 10, ...extra });

test('RANGES: 1D/1W intraday windows, then daily bar counts', () => {
  assert.deepEqual(RANGES, [['1D', { days: 1 }], ['1W', { days: 5 }], ['1M', 22], ['6M', 126], ['1Y', 252], ['5Y', 1260]]);
});

test('toBars: candles pass through and ohlc is true', () => {
  const { bars, ohlc } = toBars([candle('2026-10-30', 100), candle('2026-10-31', 101)], { daily: true });
  assert.equal(ohlc, true);
  assert.deepEqual(bars[0], { date: '2026-10-30', open: 99, high: 102, low: 98, close: 100, volume: 10 });
});

test('toBars: close-only rows give ohlc false, open=high=low=close, volume null', () => {
  const { bars, ohlc } = toBars([{ date: '2026-10-30', close: 5 }, { date: '2026-10-31', close: 6 }], { daily: true });
  assert.equal(ohlc, false);
  assert.deepEqual(bars[1], { date: '2026-10-31', open: 6, high: 6, low: 6, close: 6, volume: null });
});

test('toBars: unsorted and duplicate intraday times are sorted and deduped, last row wins', () => {
  const rows = [
    { t: '2026-10-31T09:20:00+05:30', open: 2, high: 2, low: 2, close: 2, volume: 1 },
    { t: '2026-10-31T09:15:00+05:30', open: 1, high: 1, low: 1, close: 1, volume: 1 },
    { t: '2026-10-31T09:20:00+05:30', open: 3, high: 3, low: 3, close: 3, volume: 1 },
  ];
  const { bars } = toBars(rows, { daily: false });
  assert.deepEqual(bars.map((b) => b.close), [1, 3]);
});

test('toBars: NaN or null close rows are dropped', () => {
  const { bars } = toBars([{ date: '2026-10-29', close: null }, { date: '2026-10-30', close: NaN }, { date: '2026-10-31', close: 7 }], { daily: true });
  assert.deepEqual(bars.map((b) => b.date), ['2026-10-31']);
});

test('toBars: daily cuts PriceCandle timestamps to YYYY-MM-DD; index rows read t', () => {
  assert.equal(toBars([candle('2026-10-31', 1)], { daily: true }).bars[0].date, '2026-10-31');
  assert.equal(toBars([{ t: '2026-10-31T09:15:00+05:30', close: 1 }], { daily: false }).bars[0].date, '2026-10-31T09:15:00+05:30');
  assert.deepEqual(toBars(undefined, { daily: true }), { bars: [], ohlc: false, full: [] });
});

test('visibleRanges: a daily chip shows only when it has more bars than the one before', () => {
  assert.deepEqual(visibleRanges(250), ['1D', '1W', '1M', '6M', '1Y']);
  assert.ok(visibleRanges(1300).includes('5Y'));
  assert.deepEqual(visibleRanges(1), ['1D', '1W']);
});

test('prevClose: the last bar before the session, never the session itself', () => {
  const daily = [{ date: '2026-10-29', close: 1 }, { date: '2026-10-30', close: 2 }, { date: '2026-10-31', close: 3 }];
  assert.equal(prevClose(daily, '2026-10-31'), 2);
  assert.equal(prevClose(daily, '2026-10-29'), null);
});

test('rangeChange: last close minus first close, and its percent', () => {
  assert.deepEqual(rangeChange([{ close: 100 }, { close: 105 }, { close: 110 }]), { abs: 10, pct: 10 });
  assert.equal(rangeChange([]), null);
});

test('chartTime: dates stay business days; timestamps become IST-shifted UTC seconds', () => {
  assert.equal(chartTime('2026-10-31'), '2026-10-31');
  const iso = '2026-10-31T09:15:00+05:30';
  assert.equal(chartTime(iso), Math.floor(Date.parse(iso) / 1000) + 19800);
});


test('toBars: `full` flags each bar, so one old close-only bar does not turn candles off for every range', () => {
  const rows = [{ date: '2026-10-29', close: 5 }, candle('2026-10-30', 6), candle('2026-10-31', 7)];
  const { full, ohlc } = toBars(rows, { daily: true });
  assert.deepEqual(full, [false, true, true]);
  assert.equal(ohlc, false);
  assert.equal(full.slice(-2).every(Boolean), true);
});

test('newsMarkers: intraday bars snap an item to the first bar at or after it', () => {
  const bars = ['09:15', '09:20', '09:25'].map((t, i) => ({ date: `2026-10-30T${t}:00+05:30`, close: 100 + i }));
  const n = (iso, dir = 1, impact = 6) => ({ material: true, published_at: iso, direction: dir, impact, title: iso });
  const out = newsMarkers(bars, [
    n('2026-10-30T03:51:00Z'), // 09:21 IST -> the 09:25 bar
    n('2026-10-30T03:40:00Z'), // 09:10 IST, before the first bar: dropped
    n('2026-10-30T09:00:00Z'), // 14:30 IST, after the last bar: lands on it
  ]);
  assert.deepEqual(out.map((m) => [m.date, m.count]), [['2026-10-30T09:25:00+05:30', 2]]);
});

test('newsLean: a feed item gets direction and impact from its strongest impact', () => {
  const it = newsLean({ title: 'x', impacts: [{ direction: 1, impact: 3 }, { direction: -1, impact: 7 }] });
  assert.equal(it.direction, -1);
  assert.equal(it.impact, 7);
  assert.deepEqual(newsLean({ direction: 1, impact: 4, impacts: [{ direction: -1, impact: 9 }] }).impact, 4); // symbol items keep theirs
  assert.equal(newsLean({ impacts: [] }).impact, 0);
});
