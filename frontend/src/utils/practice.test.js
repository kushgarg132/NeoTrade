import { test } from 'node:test';
import assert from 'node:assert/strict';
import { periodSummary } from './practice.js';

const now = new Date('2026-10-06T12:00:00Z');
const trades = [
  { exit_at: '2026-10-06T05:00:00Z', realized_pnl: 12, costs: 2 },
  { exit_at: '2026-10-02T05:00:00Z', realized_pnl: -3, costs: 1 },
  { exit_at: '2026-09-30T05:00:00Z', realized_pnl: 7 },
];

test('today counts only today, net of charges', () => {
  const s = periodSummary(trades, 'today', now);
  assert.equal(s.net, 10);
  assert.equal(s.trades, 1);
});

test('month is the IST calendar month', () => {
  const s = periodSummary(trades, 'month', now);
  assert.equal(s.net, 6);
  assert.equal(s.trades, 2);
  assert.equal(s.winRate, 0.5);
});

test('all time builds a cumulative curve in exit order; missing costs count as none', () => {
  const s = periodSummary(trades, 'all', now);
  assert.equal(s.net, 13);
  assert.equal(s.curve.length, 3);
  assert.deepEqual(s.curve.map((p) => p.net), [7, 3, 13]);
});

test('an IST date boundary: 23:00 IST on the 5th is not today', () => {
  const s = periodSummary([{ exit_at: '2026-10-05T17:30:00Z', realized_pnl: 5, costs: 0 }], 'today', now);
  assert.equal(s.trades, 0);
});

test('no trades: zeroes and an empty curve', () => {
  assert.deepEqual(periodSummary([], 'all', now), { net: 0, trades: 0, wins: 0, winRate: null, curve: [] });
});
