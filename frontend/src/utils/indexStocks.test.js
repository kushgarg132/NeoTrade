import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sortStocks, upDown } from './indexStocks.js';

const ROWS = [
  { symbol: 'BBB', change_pct: 1 }, { symbol: 'NOQ', change_pct: null }, { symbol: 'AAA', change_pct: -2 }, { symbol: 'CCC', change_pct: 3 },
];

test('sortStocks: by move either way, by name, no quote last, input untouched', () => {
  assert.deepEqual(sortStocks(ROWS, 'gain').map((r) => r.symbol), ['CCC', 'BBB', 'AAA', 'NOQ']);
  assert.deepEqual(sortStocks(ROWS, 'fall').map((r) => r.symbol), ['AAA', 'BBB', 'CCC', 'NOQ']);
  assert.deepEqual(sortStocks(ROWS, 'name').map((r) => r.symbol), ['AAA', 'BBB', 'CCC', 'NOQ']);
  assert.equal(ROWS[0].symbol, 'BBB');
  assert.deepEqual(sortStocks(null, 'gain'), []);
});

test('upDown skips flat and unquoted names', () => {
  assert.deepEqual(upDown([...ROWS, { symbol: 'FLAT', change_pct: 0 }]), { up: 2, down: 1 });
  assert.deepEqual(upDown(null), { up: 0, down: 0 });
});
