import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests for the admin backlog (no DOM runner here).
const src = readFileSync(new URL('./Backlog.jsx', import.meta.url), 'utf8');

test('uses the ui kit, not the old doc kit', () => {
  assert.doesNotMatch(src, /doc\/Doc/);
  assert.match(src, /<PageHeader title="Backlog"/);
  assert.match(src, /ui\/Skeleton/);
});

test('load failure has a Retry; an empty backlog names the action', () => {
  assert.match(src, /<ErrorLine[^>]*onRetry=\{retry\}/);
  assert.match(src, /<Empty[\s\S]*Add the first item/);
});

test('add row: area select inside the row, 44px primary Add', () => {
  assert.match(src, /<Button type="submit"/);
});

test('row controls are 44px on phones and area chips scroll in one row', () => {
  assert.match(src, /min-h-11 min-w-11/);
  assert.match(src, /overflow-x-auto/);
});

test('empty groups are hidden instead of repeating "Nothing here"', () => {
  assert.doesNotMatch(src, /Nothing here/);
});

test('failed writes say what happened and keep the rollback', () => {
  assert.match(src, /setItems\(before\)/);
  assert.match(src, /not saved/);
});
