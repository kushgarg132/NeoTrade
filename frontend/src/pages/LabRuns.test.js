import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./LabRuns.jsx', import.meta.url), 'utf8');

test('runs are labelled as research figures (Paper badge)', () => {
  assert.match(src, /<Badge kind="paper">/);
});
test('uses the ui kit, not the old doc kit', () => {
  assert.doesNotMatch(src, /components\/doc\/Doc/);
  assert.match(src, /ErrorLine[^\n]*onRetry/);
  assert.match(src, /<Skeleton/);
});
test('empty state names the action that fills it', () => {
  assert.match(src, /<Empty[^>]*action=/);
});
test('metrics get a plain-words gloss and CAGR carries a sign', () => {
  assert.match(src, /worst peak-to-trough fall/i);
  assert.match(src, /sign: true/);
});
test('compare shows a difference column and a pick hint', () => {
  assert.match(src, /Difference/);
  assert.match(src, /Pick two runs/);
});
