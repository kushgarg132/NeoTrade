import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dayLabel, groupNews } from './newsGroups.js';

const now = new Date('2026-10-30T12:00:00Z'); // 17:30 IST
const rows = [
  { title: 'a', at: '2026-10-30T04:00:00Z', direction: 0.5, impact: 3 },
  { title: 'b', at: '2026-10-30T06:00:00Z', direction: -0.4, impact: 8, material: true },
  { title: 'c', at: '2026-10-29T06:00:00Z', direction: 0.2, impact: 5 },
  { title: 'd', at: '2026-10-29T19:00:00Z' }, // 00:30 IST on the 30th: today in IST
  { title: 'e', at: '2026-10-20T06:00:00Z' },
  { title: 'f' },
];
const shape = (groups) => groups.map(([label, list]) => [label, list.map((r) => r.title)]);

test('days in IST, newest first, undated last', () => {
  assert.deepEqual(shape(groupNews(rows, 'all', 'newest', now)),
    [['Today', ['b', 'a', 'd']], ['Yesterday', ['c']], ['20 OCT 2026', ['e']], ['Undated', ['f']]]);
});

test('oldest first flips days and rows', () => {
  assert.deepEqual(shape(groupNews(rows, 'all', 'oldest', now)),
    [['20 OCT 2026', ['e']], ['Yesterday', ['c']], ['Today', ['d', 'a', 'b']], ['Undated', ['f']]]);
});

test('impact sorts within a day, unscored last', () => {
  assert.deepEqual(shape(groupNews(rows, 'all', 'impact', now))[0], ['Today', ['b', 'a', 'd']]);
  const flip = rows.map((r) => (r.title === 'a' ? { ...r, impact: 9 } : r));
  assert.deepEqual(shape(groupNews(flip, 'all', 'impact', now))[0], ['Today', ['a', 'b', 'd']]);
});

test('filters by direction sign and materiality', () => {
  assert.deepEqual(shape(groupNews(rows, 'up', 'newest', now)), [['Today', ['a']], ['Yesterday', ['c']]]);
  assert.deepEqual(shape(groupNews(rows, 'down', 'newest', now)), [['Today', ['b']]]);
  assert.deepEqual(shape(groupNews(rows, 'material', 'newest', now)), [['Today', ['b']]]);
});

test('dayLabel', () => {
  assert.equal(dayLabel(null, now), 'Undated');
  assert.equal(dayLabel('2026-10-29T18:29:00Z', now), 'Yesterday'); // 23:59 IST
});
