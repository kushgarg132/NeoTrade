import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Strategies.jsx', import.meta.url), 'utf8');

test('page uses the ui kit, not the doc Sheet/Ruling', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.match(src, /components\/ui\/Card/);
  assert.match(src, /components\/ui\/Skeleton/);
});

test('library load failure has a Retry and an Empty that names the action', () => {
  assert.match(src, /<ErrorLine[^>]*onRetry/);
  assert.match(src, /<Empty[\s\S]*?action=/);
});

test('record line carries the Paper label and the gate is not worded as live', () => {
  assert.match(src, /kind="paper"/);
  assert.match(src, /Passes the live gate/);
  assert.doesNotMatch(src, /label: 'Ready for real money'/);
});

test('responses are read null-safely', () => {
  assert.match(src, /res\.data\?\.strategies \?\? \[\]/);
  assert.match(src, /\(res\.data \?\? \[\]\)\.map/);
});

test('collapsed rows leave built description for the expanded part', () => {
  const head = src.split('{open && (')[0];
  assert.doesNotMatch(head, /card\.built\.description/);
});
