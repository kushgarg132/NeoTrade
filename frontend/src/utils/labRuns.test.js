import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compareRows, flatMetrics, fmtMetric } from './labRuns.js';

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

const S = { cagr: 0.2, sharpe: 1.1, sortino: 1.5, max_drawdown: -0.1, volatility: 0.15, alpha: null, beta: null };

test('flatMetrics: gate payload', () => {
  const f = flatMetrics({ trades: 5, pf: 1.2, dd: 0.1, net: 100, summary: S });
  assert.equal(f.cagr, 0.2); assert.equal(f.max_drawdown, -0.1); assert.equal(f.trades, 5); assert.ok(!('alpha' in f));
});

test('flatMetrics: factor payload (oos, vol alias)', () => {
  const f = flatMetrics({ oos: { cagr: 0.3, vol: 0.2, sharpe: 1.4, max_drawdown: -0.2, calmar: 1.5 }, dsr: 0.9, verdict: { passed: true } });
  assert.deepEqual([f.cagr, f.sharpe, f.max_drawdown, f.volatility, f.dsr], [0.3, 1.4, -0.2, 0.2, 0.9]);
});

test('flatMetrics: retune payload falls back to test.best', () => {
  const f = flatMetrics({ accepted: true, train: { '{"a":1}': { trades: 9, net: 1, sharpe: 0.1 } }, test: { best: { trades: 4, net: 50, sharpe: 0.8 }, current: { trades: 3, net: 5, sharpe: 0.2 } } });
  assert.equal(f.sharpe, 0.8); assert.equal(f.cagr, undefined);
});

test('flatMetrics: builder payload', () => {
  const f = flatMetrics({ year: { trades: 3 }, holdout: { net: 2 }, sharpe: 0.7 });
  assert.equal(f.sharpe, 0.7); assert.equal(f.cagr, undefined);
});

test('flatMetrics: study payload has no cagr/sharpe/drawdown', () => {
  const f = flatMetrics({ n: 120, mean: 0.01, hit_rate: 0.55, years: [{ year: 2024, n: 10 }] });
  assert.equal(f.n, 120); assert.equal(f.cagr, undefined); assert.equal(f.sharpe, undefined);
});

test('fmtMetric', () => {
  assert.equal(fmtMetric('cagr', 0.2794), '27.9%');
  assert.equal(fmtMetric('sharpe', 1.234), '1.23');
  assert.equal(fmtMetric('trades', 5), '5.000');
  assert.equal(fmtMetric('cagr', undefined), '—');
});
