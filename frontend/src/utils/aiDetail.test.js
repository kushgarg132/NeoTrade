import { test } from 'node:test';
import assert from 'node:assert/strict';
import { openTradeIds, strategyRow, strategyStatus, tradeSummary } from './aiDetail.js';

test('strategyRow finds by name, null when absent', () => {
  const card = { strategies: [{ strategy: 'a', net: 1 }] };
  assert.equal(strategyRow(card, 'a').net, 1);
  assert.equal(strategyRow(card, 'nope'), null);
  assert.equal(strategyRow(null, 'a'), null);
});

test('strategyStatus: parked wins, then paused, then the badge', () => {
  const badge = { tone: 'success' };
  assert.equal(strategyStatus({ row: { parked: true }, badge, paused: ['x'], name: 'x' }).label, 'Parked');
  assert.equal(strategyStatus({ row: {}, badge, paused: ['x'], name: 'x' }).label, 'Paused');
  assert.equal(strategyStatus({ row: {}, badge, paused: ['x'], name: 'y' }).label, 'Proven');
  assert.equal(strategyStatus({ row: null, badge: null, paused: [] }).label, 'Unproven');
});

test('tradeSummary: open has no net, closed nets costs', () => {
  const o = tradeSummary({ status: 'OPEN', costs: 12 });
  assert.equal(o.open, true);
  assert.equal(o.net, null);
  const c = tradeSummary({ status: 'CLOSED', realized_pnl: 100, costs: 12, entry_at: '2026-10-01T04:00:00Z', exit_at: '2026-10-03T04:00:00Z' });
  assert.equal(c.net, 88);
  assert.equal(c.gross, 100);
  assert.equal(c.held, '2d');
});

test('openTradeIds maps each open trade symbol to its id; no trade -> undefined', () => {
  const ids = openTradeIds([{ id: 'a', symbol: 'TCS', status: 'OPEN' }, { id: 'b', symbol: 'INFY', status: 'OPEN' }, { id: 'c', symbol: 'SBIN', status: 'CLOSED' }]);
  assert.deepEqual(ids, { TCS: 'a', INFY: 'b' });
  assert.equal(ids.SBIN, undefined);
  assert.deepEqual(openTradeIds(null), {});
});

test('openTradeIds drops a symbol with two open trades so the row links to the stock', () => {
  const ids = openTradeIds([{ id: 'a', symbol: 'TCS', status: 'OPEN' }, { id: 'b', symbol: 'TCS', status: 'OPEN' }, { id: 'c', symbol: 'INFY', status: 'OPEN' }]);
  assert.equal(ids.TCS, null);
  assert.equal(ids.INFY, 'c');
});
