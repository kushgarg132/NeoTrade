import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sortHoldings, topMovers, whyLine, MARKET_WHY } from './money.js';

const rows = [
  { symbol: 'A', last_price: 110, close_price: 100, quantity: 10, value: 1100, weight_pct: 20, pnl_pct: 0.1 },
  { symbol: 'B', last_price: 190, close_price: 200, quantity: 100, value: 19000, weight_pct: 60, pnl_pct: -0.05 },
  { symbol: 'C', value: 500, weight_pct: 5 },
  { symbol: 'D', last_price: 50, close_price: 49, quantity: 1, value: 50, weight_pct: 1, pnl_pct: 0.3 },
];

test('sortHoldings by key, missing figures last, input untouched', () => {
  assert.deepEqual(sortHoldings(rows, 'value').map((r) => r.symbol), ['B', 'A', 'C', 'D']);
  assert.deepEqual(sortHoldings(rows, 'pnl').map((r) => r.symbol), ['D', 'A', 'B', 'C']);
  assert.deepEqual(sortHoldings(rows, 'day').map((r) => r.symbol), ['A', 'D', 'B', 'C']);
  assert.equal(rows[0].symbol, 'A');
});

test('topMovers ranks by rupee move and skips unpriced rows', () => {
  const m = topMovers(rows, 3);
  assert.deepEqual(m.map((r) => r.symbol), ['B', 'A', 'D']);
  assert.equal(m[0].day_rupees, -1000);
  assert.ok(Math.abs(m[0].day_pct + 0.05) < 1e-9);
});

test('whyLine: headline, then verdict reason, then the market fallback', () => {
  assert.equal(whyLine({ news: { headline: 'Q2 profit up 12%' }, reason_codes: ['uptrend'] }), 'Q2 profit up 12%');
  assert.match(whyLine({ reason_codes: ['nope', 'below_200dma'] }), /200-day/);
  assert.equal(whyLine({}), MARKET_WHY);
  assert.equal(MARKET_WHY, 'Moved with the market');
});
