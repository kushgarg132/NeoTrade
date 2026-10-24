import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Profile.jsx', import.meta.url), 'utf8');

test('uses the ui kit, not the old doc kit', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.doesNotMatch(src, /doc-meta|field-label/);
  assert.match(src, /ui\/Card/);
  assert.match(src, /ui\/PageHeader/);
});

test('load failure has a Retry and says what is affected', () => {
  assert.match(src, /ErrorLine/);
  assert.match(src, /Couldn.t load your profile/);
  assert.match(src, /onRetry/);
});

test('memory empty state names the action; fields say who reads them', () => {
  assert.match(src, /<Empty[^>]*action=/);
  assert.match(src, /Risk appetite/);
  assert.match(src, /RISK_HELP/);
  assert.match(src, /Used in every chat/);
});

test('inputs are at least 44px tall', () => {
  assert.match(src, /min-h-11/);
  assert.doesNotMatch(src, /h-8\b/);
});
