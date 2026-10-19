import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actionTarget, targetProgress, sortHoldings, formatXirr, RANGES, holdingsStale, taxYears } from './mine.js';

test('holdingsStale only past 36 hours (I9: logged in reads as fresh)', () => {
  const now = Date.parse('2026-10-15T10:00:00Z');
  assert.equal(holdingsStale('2026-10-15T09:59:00Z', now), false);
  assert.equal(holdingsStale('2026-10-13T21:00:00Z', now), true);
  assert.equal(holdingsStale(null, now), false);
});

test('taxYears runs from the current FY back to 2025 only (I5)', () => {
  assert.deepEqual(taxYears(2026), [2026, 2025]);
  assert.deepEqual(taxYears(2025), [2025]);
});

test('actionTarget maps every type', () => {
  const t = (action) => actionTarget({ symbol: 'TCS', action });
  assert.deepEqual(t({ type: 'stock' }), { to: '/stock/TCS' });
  assert.deepEqual(t({ type: 'tax' }), { to: '/portfolio/tax' });
  assert.deepEqual(t({ type: 'rebalance' }), { to: '/portfolio/holdings?plan=1' });
  assert.deepEqual(t({ type: 'ticket', side: 'SELL', quantity: 5, price: 90 }), {
    ticket: { symbol: 'TCS', side: 'SELL', quantity: 5, limitPrice: 90 },
  });
  assert.deepEqual(t({ type: 'idea', suggestion_id: 'abc' }), { to: '/portfolio', idea: 'abc' });
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

test('floorAtZero pads below but never under zero for non-negative data', async () => {
  const { floorAtZero } = await import('./mine.js');
  assert.equal(floorAtZero(1000), 950);
  assert.equal(floorAtZero(0), 0);
  assert.equal(floorAtZero(-50), -50);
});
