import { test } from 'node:test';
import assert from 'node:assert/strict';
import { advance, byStatus, counts, filterItems, stageTime, timeline } from './backlog.js';

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

test('byStatus: newest first by the time that fits the stage', () => {
  const day = (d) => `2026-11-0${d}T10:00:00Z`;
  const rows = [
    { id: 1, status: 'doing', created_at: day(9), started_at: day(1) },
    { id: 2, status: 'doing', created_at: day(2), started_at: day(3) },
    { id: 3, status: 'doing', created_at: day(4), started_at: null }, // an older item without a start: when it was added
    { id: 4, status: 'done', created_at: day(9), done_at: day(1) },
    { id: 5, status: 'done', created_at: day(1), done_at: day(2) },
    { id: 6, status: 'dropped', created_at: day(9), updated_at: day(1) },
    { id: 7, status: 'dropped', created_at: day(1), updated_at: day(2) },
    { id: 8, status: 'idea', created_at: day(1), updated_at: day(9) },
    { id: 9, status: 'idea', created_at: day(2), updated_at: day(1) },
  ];
  assert.deepEqual(byStatus(rows, 'doing').map((i) => i.id), [3, 2, 1]);
  assert.deepEqual(byStatus(rows, 'done').map((i) => i.id), [5, 4]);
  assert.deepEqual(byStatus(rows, 'dropped').map((i) => i.id), [7, 6]);
  assert.deepEqual(byStatus(rows, 'idea').map((i) => i.id), [9, 8]);
});

test('groups and counts per status', () => {
  assert.equal(byStatus(ITEMS, 'next').length, 2);
  assert.deepEqual(counts(ITEMS), { idea: 1, next: 2, doing: 0, done: 0, dropped: 0 });
});

test('stageTime picks the time that fits the stage', () => {
  const ago = (hours) => new Date(Date.now() - hours * 3600e3).toISOString();
  const item = { created_at: ago(72), started_at: ago(2), done_at: ago(1), updated_at: ago(5) };
  assert.equal(stageTime({ ...item, status: 'idea' }), 'added 3d ago');
  assert.equal(stageTime({ ...item, status: 'next' }), 'added 3d ago');
  assert.equal(stageTime({ ...item, status: 'doing' }), 'started 2h ago');
  assert.equal(stageTime({ ...item, status: 'doing', started_at: null }), 'added 3d ago');
  assert.equal(stageTime({ ...item, status: 'done' }), 'done 1h ago');
  assert.equal(stageTime({ ...item, status: 'dropped' }), 'dropped 5h ago');
  assert.equal(stageTime({ status: 'done', done_at: null }), '');
});

test('timeline keeps order and leaves out empty times', () => {
  const at = '2026-11-02T10:00:00Z';
  assert.deepEqual(timeline({ created_at: at, started_at: null, done_at: null, updated_at: at }).map((t) => t.label), ['Added', 'Updated']);
  assert.deepEqual(timeline({ created_at: at, started_at: at, done_at: at, updated_at: at }).map((t) => t.label), ['Added', 'Started', 'Done', 'Updated']);
});
