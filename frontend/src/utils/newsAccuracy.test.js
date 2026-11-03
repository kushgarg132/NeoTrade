import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rowsFor, hitTone, barRows } from './newsAccuracy.js';

const cell = (group, key, impact, measure, extra = {}) =>
  ({ group, scope: 'COMPANY', key, impact, horizon: '5d', measure, n: 40, hit: 0.5, thin: false, ...extra });

test('rowsFor keeps one scope and horizon, total first, then themes, sources, models', () => {
  const cells = [
    cell('model', 'm1', 'all', 'move'),
    cell('theme', 'orders', 'all', 'move'),
    cell('theme', 'all', '>=7', 'move'),
    cell('theme', 'all', 'all', 'pre_move'),
    cell('theme', 'all', 'all', 'move'),
    cell('source', 'Mint', 'all', 'move'),
    cell('theme', 'all', 'all', 'move', { scope: 'SECTOR' }),
    cell('theme', 'all', 'all', 'move', { horizon: '1d' }),
  ];
  const rows = rowsFor(cells, 'COMPANY', '5d').map((c) => `${c.group}:${c.key}:${c.impact}:${c.measure}`);
  assert.deepEqual(rows, ['theme:all:all:move', 'theme:all:all:pre_move', 'theme:all:>=7:move',
    'theme:orders:all:move', 'source:Mint:all:move', 'model:m1:all:move']);
  assert.deepEqual(rowsFor(undefined, 'COMPANY', '5d'), []);
});

test('hitTone: green from 52%, red to 48%, plain between and for thin cells', () => {
  assert.equal(hitTone({ hit: 0.52 }), 'gain');
  assert.equal(hitTone({ hit: 0.48 }), 'loss');
  assert.equal(hitTone({ hit: 0.5 }), 'neutral');
  assert.equal(hitTone({ hit: 0.9, thin: true }), 'neutral');
});

test('barRows shows the standing against the fixed bar, and a dash with no data', () => {
  assert.deepEqual(barRows({ n: 12, days: 5, mean: 0.0012, t: 1.25 }), [
    ['Signals', '12 of 100'], ['Trading days', '5 of 20'], ['Average per trade, after charges', '+0.12%'], ['t, needs 2', '1.3'],
  ]);
  assert.equal(barRows({ n: 0, days: 0, mean: null, t: null })[2][1], '–');
});

test('rowsFor gives a stable order with the prompt and priced_in groups', () => {
  const cell = (group, key) => ({ group, key, scope: 'COMPANY', horizon: '5d', impact: 'all', measure: 'move' });
  const rows = rowsFor([cell('priced_in', 'fresh'), cell('prompt', 'p@2'), cell('model', 'm'), cell('theme', 'all')], 'COMPANY', '5d');
  assert.deepEqual(rows.map((r) => r.group), ['theme', 'model', 'prompt', 'priced_in']);
});
