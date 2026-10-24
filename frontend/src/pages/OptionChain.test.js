import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./OptionChain.jsx', import.meta.url), 'utf8');

test('page uses the ui kit, not the doc Sheet/Field/Ruling', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.match(src, /components\/ui\/Tabs/);
  assert.match(src, /components\/ui\/Skeleton/);
});

test('errors have Retry; empty expiry list names an action', () => {
  assert.match(src, /<ErrorLine[^>]*onRetry/);
  assert.match(src, /<Empty[\s\S]*?action=/);
});

test('refresh button announces busy and chain shows fetch time', () => {
  assert.match(src, /aria-busy=\{busy\}/);
  assert.match(src, /Fetched/);
});

test('the ATM row is marked in text, not colour alone', () => {
  assert.match(src, />ATM</);
});

test('nothing smaller than 12px', () => {
  assert.doesNotMatch(src, /text-\[(\d|1[01])px\]/);
});
