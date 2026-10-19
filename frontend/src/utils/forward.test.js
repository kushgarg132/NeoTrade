import { test } from 'node:test';
import assert from 'node:assert/strict';
import { badgeFor } from './forward.js';

const rows = [
  { source: 'picks', name: 'a', n: 140, label: 'proven' },
  { source: 'engine', name: 'b', n: 37, label: 'unproven' },
];

test('proven row says Proven', () => {
  assert.deepEqual(badgeFor(rows, 'picks', 'a'), { text: 'Proven', tone: 'success' });
});
test('unproven row shows progress toward 100', () => {
  assert.equal(badgeFor(rows, 'engine', 'b').text, 'Unproven 37/100');
});
test('no row means no badge', () => {
  assert.equal(badgeFor(rows, 'engine', 'zzz'), null);
  assert.equal(badgeFor(undefined, 'engine', 'b'), null);
});
