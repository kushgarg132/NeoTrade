import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compareRows } from './labRuns.js';

const full = { cagr: 1, sharpe: 2, sortino: 3, max_drawdown: -4, volatility: 5, alpha: 6, beta: 7 };

test('returns the 7 summary keys in order', () => {
  const rows = compareRows({ metrics: full }, { metrics: { ...full, cagr: 9 } });
  assert.deepEqual(rows.map((r) => r.key), ['cagr', 'sharpe', 'sortino', 'max_drawdown', 'volatility', 'alpha', 'beta']);
  assert.deepEqual(rows[0], { key: 'cagr', a: 1, b: 9 });
});

test('skips a key missing from one side and adds shared kind-specific keys', () => {
  const { beta, ...noBeta } = full;
  const rows = compareRows({ metrics: { ...noBeta, trades: 5, pf: 1 } }, { metrics: { ...full, trades: 8, dd: 2 } });
  assert.ok(!rows.some((r) => r.key === 'beta' || r.key === 'pf' || r.key === 'dd'));
  assert.deepEqual(rows.at(-1), { key: 'trades', a: 5, b: 8 });
});
