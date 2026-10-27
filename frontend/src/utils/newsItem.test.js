import { test } from 'node:test';
import assert from 'node:assert/strict';
import { outcomeRows } from './newsItem.js';

test('no outcomes is an empty list', () => {
  assert.deepEqual(outcomeRows([]), []);
  assert.deepEqual(outcomeRows(undefined), []);
});

test('a row with only the 1d horizon yields one entry, vsBench = ret - bench', () => {
  const rows = outcomeRows([{ target: 'TCS', ret_1d: 0.02, bench_1d: 0.005 }]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].target, 'TCS');
  assert.equal(rows[0].horizon, '1d');
  assert.equal(rows[0].move, 0.02);
  assert.ok(Math.abs(rows[0].vsBench - 0.015) < 1e-9);
});

test('horizons come out 1h, 1d, 5d', () => {
  const rows = outcomeRows([{ target: 'A', ret_5d: 0.1, bench_5d: 0.1, ret_1h: 0.01, bench_1h: 0 }]);
  assert.deepEqual(rows.map((r) => r.horizon), ['1h', '5d']);
});
