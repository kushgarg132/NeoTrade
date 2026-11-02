import { test } from 'node:test';
import assert from 'node:assert/strict';
import { byDay, matchLean } from './news.js';
import { filterSectors } from './market.js';

test('byDay groups by IST day, newest first, Today / Yesterday / weekday labels', () => {
  const now = Date.parse('2026-10-31T10:00:00Z'); // Sat 15:30 IST
  const items = [
    { id: 'a', published_at: '2026-10-31T09:00:00Z' },
    { id: 'b', published_at: '2026-10-30T19:00:00Z' }, // 00:30 IST on the 31st
    { id: 'c', published_at: '2026-10-30T18:00:00Z' }, // 23:30 IST on the 30th
    { id: 'd', published_at: '2026-10-29T05:00:00Z' },
    { id: 'e', published_at: '2026-10-29T04:00:00Z' },
  ];
  const groups = byDay(items, now);
  assert.deepEqual(groups.map((g) => g.label), ['Today', 'Yesterday', 'Thu 29 Oct']);
  assert.deepEqual(groups.map((g) => g.items.map((i) => i.id)), [['a', 'b'], ['c'], ['d', 'e']]);
  assert.deepEqual(byDay([], now), []);
});

test('byDay keeps one header when a day spans two pages and drops undated items into no group', () => {
  const now = Date.parse('2026-10-31T10:00:00Z');
  const groups = byDay([{ id: 'x', published_at: '2026-10-28T05:00:00Z' }, { id: 'y', published_at: '2026-10-28T03:00:00Z' }], now);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].items.length, 2);
});

test('matchLean reads the strongest impact; empty lean keeps everything', () => {
  const up = { impacts: [{ impact: 3, direction: -1 }, { impact: 7, direction: 0.6 }] };
  const down = { impacts: [{ impact: 8, direction: -0.5 }] };
  const none = { impacts: [] };
  assert.equal(matchLean(up, 'up'), true);
  assert.equal(matchLean(up, 'down'), false);
  assert.equal(matchLean(down, 'down'), true);
  assert.equal(matchLean(none, 'up'), false);
  assert.equal(matchLean(none, 'down'), false);
  assert.equal(matchLean(none, ''), true);
});

test('filterSectors: up, down, flagged; all keeps the list', () => {
  const rows = [
    { sector: 'A', change_pct: 1.2, sentiment: -0.5 },
    { sector: 'B', change_pct: -0.4, sentiment: -0.5 },
    { sector: 'C', change_pct: 0, sentiment: null },
  ];
  assert.deepEqual(filterSectors(rows, 'all').map((r) => r.sector), ['A', 'B', 'C']);
  assert.deepEqual(filterSectors(rows, 'up').map((r) => r.sector), ['A']);
  assert.deepEqual(filterSectors(rows, 'down').map((r) => r.sector), ['B']);
  assert.deepEqual(filterSectors(rows, 'flagged').map((r) => r.sector), ['A']);
});
