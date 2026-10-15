import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actionTarget, targetProgress, sortHoldings, formatXirr, RANGES } from './mine.js';

test('actionTarget maps every type', () => {
  const t = (action) => actionTarget({ symbol: 'TCS', action });
  assert.deepEqual(t({ type: 'stock' }), { to: '/mine/stock/TCS' });
  assert.deepEqual(t({ type: 'tax' }), { to: '/mine/tax' });
  assert.deepEqual(t({ type: 'rebalance' }), { to: '/mine/holdings?plan=1' });
  assert.deepEqual(t({ type: 'ticket', side: 'SELL', quantity: 5, price: 90 }), {
    ticket: { symbol: 'TCS', side: 'SELL', quantity: 5, limitPrice: 90 },
  });
  assert.deepEqual(t({ type: 'idea', suggestion_id: 'abc' }), { to: '/mine', idea: 'abc' });
  assert.deepEqual(t({ type: 'none' }), {});
});

test('targetProgress clamps and needs a target', () => {
  assert.equal(targetProgress(100, 150, 200), 0.5);
  assert.equal(targetProgress(100, 250, 200), 1);
  assert.equal(targetProgress(100, 90, 200), 0);
  assert.equal(targetProgress(100, 90, null), null);
});

test('formatXirr', () => {
  assert.equal(formatXirr(null), '—');
  assert.equal(formatXirr(0.1234), '12.3%');
});

test('sortHoldings by verdict puts SELL first', () => {
  const rows = [{ symbol: 'A', verdict: 'HOLD' }, { symbol: 'B', verdict: 'SELL' }, { symbol: 'C', verdict: 'ADD' }];
  assert.equal(sortHoldings(rows, 'verdict')[0].symbol, 'B');
  assert.deepEqual(RANGES, ['1M', '6M', '1Y', 'ALL']);
});
