import { test } from 'node:test';
import assert from 'node:assert/strict';
import { marketPhase } from './formatters.js';

// NSE in IST: pre-open 09:00-09:15, open 09:15-15:30, weekdays; everything else is closed.
test('market phase follows the NSE session, not just the clock before the open', () => {
  assert.equal(marketPhase(new Date('2026-10-06T18:37:00Z')), 'closed'); // Wed 00:07 IST
  assert.equal(marketPhase(new Date('2026-10-07T03:35:00Z')), 'pre'); // Wed 09:05 IST
  assert.equal(marketPhase(new Date('2026-10-07T04:00:00Z')), 'open'); // Wed 09:30 IST
  assert.equal(marketPhase(new Date('2026-10-07T10:05:00Z')), 'closed'); // Wed 15:35 IST
  assert.equal(marketPhase(new Date('2026-10-04T04:00:00Z')), 'closed'); // Sunday
});
