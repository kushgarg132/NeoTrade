import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countdown, daysUntil, dividendRows, eventTitle, sourceOf, todayIst } from './events.js';

test('titles, countdowns, IST today', () => {
  assert.equal(eventTitle({ kind: 'results' }), 'Quarterly results');
  assert.equal(eventTitle({ kind: 'board_meeting' }), 'board meeting');
  assert.equal(daysUntil('2026-11-12', '2026-10-30'), 13);
  assert.deepEqual([0, 1, 13, -2].map(countdown), ['Today', 'Tomorrow', 'In 13 days', '2 days ago']);
  assert.equal(todayIst(new Date('2026-10-30T19:00:00Z')), '2026-10-31'); // 00:30 IST
});

test('sourceOf', () => {
  assert.equal(sourceOf('Hindustan Copper: Citi initiates coverage - Business Upturn'), 'Business Upturn');
  assert.equal(sourceOf('Hindustan Copper Limited: General Updates'), null);
  assert.equal(sourceOf(undefined), null);
});

test('dividendRows: history with what you got, newest first, and the total', () => {
  const past = [{ date: '2026-09-16', per_share: 1.86 }, { date: '2026-02-13', per_share: 1.0 }];
  const received = [{ date: '2026-09-16', per_share: 1.86, qty: 32, amount: 59.52 },
    { date: '2025-09-18', per_share: 1.46, qty: 10, amount: 14.6 }]; // older than the history kept
  const { rows, total } = dividendRows(past, received);
  assert.deepEqual(rows.map((r) => [r.date, r.perShare, r.amount]),
    [['2026-09-16', 1.86, 59.52], ['2026-02-13', 1.0, undefined], ['2025-09-18', 1.46, 14.6]]);
  assert.equal(Math.round(total * 100) / 100, 74.12);
  assert.deepEqual(dividendRows(), { rows: [], total: 0 });
});
