import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fyStart } from './months.js';

test('fyStart: the financial year starts in April, judged on the IST day', () => {
  assert.equal(fyStart('2027-03-31'), 2026);
  assert.equal(fyStart('2027-04-01'), 2027);
  assert.equal(fyStart('2026-12-15'), 2026);
});
