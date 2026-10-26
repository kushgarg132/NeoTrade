import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rowsFor, hitTone } from './newsAccuracy.js';

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
