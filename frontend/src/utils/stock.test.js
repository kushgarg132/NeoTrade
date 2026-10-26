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
