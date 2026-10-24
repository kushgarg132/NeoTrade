import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./LabForward.jsx', import.meta.url), 'utf8');

test('forward figures carry the Paper label', () => {
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
test('jargon has a gloss and outcomes carry a sign', () => {
  assert.match(src, /Hit rate = /);
  assert.match(src, /sign: true/);
});
test('open row keeps the row object (title bug) and records open inline', () => {
  assert.match(src, /useState\(null\);\s*\n\s*const \[records/);
  assert.doesNotMatch(src, /\{open\.source\}/);
});
