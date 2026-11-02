import { test } from 'node:test';
import assert from 'node:assert/strict';
import { advance, byStatus, counts, filterItems } from './backlog.js';

const ITEMS = [
  { id: 1, title: 'Rotation scorecard', why: 'live gate', notes: '', area: 'Trading', effort: 'M', status: 'next', rank: 2 },
  { id: 2, title: 'Onboarding', why: 'empty pages', notes: 'three steps', area: 'UI', effort: 'M', status: 'next', rank: 1 },
  { id: 3, title: 'Share card', why: '', notes: '', area: 'UI', effort: 'S', status: 'idea', rank: 0 },
];

test('advance moves one stage forward and stops at the end', () => {
  assert.deepEqual(advance('idea'), { to: 'next', label: 'Next' });
  assert.deepEqual(advance('next'), { to: 'doing', label: 'Start' });
  assert.deepEqual(advance('doing'), { to: 'done', label: 'Done' });
  assert.equal(advance('done'), null);
});

test('filter by words across title, why and notes, area and effort', () => {
  assert.deepEqual(filterItems(ITEMS, { q: 'three' }).map((i) => i.id), [2]);
  assert.deepEqual(filterItems(ITEMS, { q: 'ROTATION gate' }).map((i) => i.id), [1]);
  assert.deepEqual(filterItems(ITEMS, { area: 'UI', effort: 'S' }).map((i) => i.id), [3]);
  assert.equal(filterItems(ITEMS).length, 3);
});

test('groups in rank order and counts per status', () => {
  assert.deepEqual(byStatus(ITEMS, 'next').map((i) => i.id), [2, 1]);
  assert.deepEqual(counts(ITEMS), { idea: 1, next: 2, doing: 0, done: 0, dropped: 0 });
});
