import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatClock, marketPhase } from './formatters.js';

// NSE in IST: pre-open 09:00-09:15, open 09:15-15:30, weekdays; everything else is closed.
test('market phase follows the NSE session, not just the clock before the open', () => {
  assert.equal(marketPhase(new Date('2026-10-06T18:37:00Z')), 'closed'); // Wed 00:07 IST
  assert.equal(marketPhase(new Date('2026-10-07T03:35:00Z')), 'pre'); // Wed 09:05 IST
  assert.equal(marketPhase(new Date('2026-10-07T04:00:00Z')), 'open'); // Wed 09:30 IST
  assert.equal(marketPhase(new Date('2026-10-07T10:05:00Z')), 'closed'); // Wed 15:35 IST
  assert.equal(marketPhase(new Date('2026-10-04T04:00:00Z')), 'closed'); // Sunday
});

test('formatClock: 12-hour IST', () => {
  assert.equal(formatClock('2026-10-07T09:50:00Z'), '3:20 PM');
  assert.equal(formatClock('2026-10-07T03:45:00Z'), '9:15 AM');
  assert.equal(formatClock('2026-10-06T18:30:00Z'), '12:00 AM');
  assert.equal(formatClock(null), '—');
});

test('asOf: clock in session, stale past 15 min; closed says last close, dated after a long weekend', async () => {
  const { asOf } = await import('./formatters.js');
  const now = Date.parse('2026-10-23T09:00:00Z'); // Fri 14:30 IST
  assert.equal(asOf(null), null);
  assert.deepEqual(asOf(now / 1000 - 60, 'open', now), { text: 'as of 2:29 PM', stale: false });
  assert.equal(asOf(now - 16 * 60_000, 'session', now).stale, true);
  assert.deepEqual(asOf(now - 3_600_000, 'closed', now), { text: 'Market closed · last close', stale: false });
  const old = asOf(now - 5 * 86_400_000, 'post', now);
  assert.equal(old.stale, true);
  assert.match(old.text, /^as of 18 OCT 2026/);
});
