import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shiftWeek, weekRange } from './weekly.js';

test('shiftWeek moves by weeks and crosses year ends', () => {
  assert.equal(shiftWeek('2026-W42', -1), '2026-W41');
  assert.equal(shiftWeek('2026-W42', 1), '2026-W43');
  assert.equal(shiftWeek('2026-W01', -1), '2025-W52');
  assert.equal(shiftWeek('2020-W53', 1), '2021-W01');
  assert.equal(shiftWeek('2026-W53', 0), '2026-W53');
});

test('weekRange is Monday to Sunday', () => {
  assert.equal(weekRange('2026-W42'), '12 Oct - 18 Oct');
});
