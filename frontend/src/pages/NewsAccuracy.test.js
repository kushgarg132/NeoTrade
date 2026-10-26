import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./NewsAccuracy.jsx', import.meta.url), 'utf8');

test('uses the ui kit with loading, retry and an empty state that names the action', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.match(src, /<Skeleton/);
  assert.match(src, /<ErrorLine[^>]*onRetry=/);
  assert.match(src, /<Empty[^>]*action=/);
});
test('filters by scope and horizon, fades thin cells, glosses the jargon', () => {
  assert.match(src, /aria-label="Scope"/);
  assert.match(src, /aria-label="Horizon"/);
  assert.match(src, /c\.thin \? 'opacity-50'/);
  assert.match(src, /Hit rate = /);
  assert.match(src, /endpoints\.newsAccuracy/);
});
