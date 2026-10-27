import test from 'node:test';
import assert from 'node:assert/strict';
import { holdTime } from './roundTrip.js';

const NOW = new Date('2026-10-27T10:00:00Z');

test('closed trips read in days', () => {
  assert.equal(holdTime('2026-10-20T04:00:00Z', '2026-10-22T04:00:00Z', NOW), '2 days');
  assert.equal(holdTime('2026-10-20T04:00:00Z', '2026-10-21T04:00:00Z', NOW), '1 day');
});
test('same-day trips read in hours, then minutes', () => {
  assert.equal(holdTime('2026-10-27T04:00:00Z', '2026-10-27T06:00:00Z', NOW), '2 h');
  assert.equal(holdTime('2026-10-27T04:00:00Z', '2026-10-27T04:20:00Z', NOW), '20 min');
});
test('open trips are prefixed and measured to now', () => {
  assert.equal(holdTime('2026-10-22T10:00:00Z', null, NOW), 'Open · 5 days');
  assert.equal(holdTime('2026-10-27T07:00:00Z', null, NOW), 'Open · 3 h');
});
