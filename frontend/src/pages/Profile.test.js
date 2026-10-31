import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Profile.jsx', import.meta.url), 'utf8');

test('uses the ui kit, not the old doc kit', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.doesNotMatch(src, /doc-meta|field-label/);
  assert.match(src, /ui\/PageHeader/);
});

test('load failure has a Retry and says what is affected', () => {
  assert.match(src, /ErrorLine/);
  assert.match(src, /Couldn.t load your profile/);
  assert.match(src, /onRetry/);
});

test('sections read as sentences and edit in place with one Save each', () => {
  assert.match(src, /const Section = /);
  assert.match(src, /read=\{tradeLines\}/);
  assert.match(src, /setEditing\(false\)/);
});

test('empty states name the action; fields say who reads them', () => {
  assert.match(src, /emptyText=/);
  assert.match(src, /Nothing remembered yet\. Tell the assistant/);
  assert.match(src, /Risk appetite/);
  assert.match(src, /RISK_HELP/);
  assert.match(src, /Used in every chat/);
});

test('inputs are at least 44px tall', () => {
  assert.match(src, /min-h-11/);
  assert.doesNotMatch(src, /h-8\b/);
});
