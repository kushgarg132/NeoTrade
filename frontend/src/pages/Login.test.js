import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Login.jsx', import.meta.url), 'utf8');

test('uses ui primitives, not the doc kit', () => {
  assert.match(src, /components\/ui\/Badge/);
  assert.doesNotMatch(src, /sheet|doc-meta|field-label|formatNoteDate|Contract Note/);
});

test('copy matches the app: no stale Journal/Patterns/Guardrails pitch', () => {
  assert.doesNotMatch(src, /Journal|Patterns|Guardrails/);
  assert.match(src, /paper/i);
  assert.match(src, /Not investment advice/);
});

test('auth flow is intact', () => {
  assert.match(src, /login\(credentialResponse\.credential\)/);
  assert.match(src, /params\.get\('request_token'\)/);
  assert.match(src, /select-all/);
});

test('glow card and big wordmark', () => {
  assert.match(src, /var\(--glow\)/);
  assert.match(src, /rounded-\[28px\]/);
  assert.match(src, /text-\[44px\]/);
  assert.match(src, /font-extrabold/);
  assert.doesNotMatch(src, /components\/ui\/Card/);
});

test('error uses soft loss fill and keeps role=alert', () => {
  assert.match(src, /role="alert"/);
  assert.match(src, /--loss-soft/);
  assert.doesNotMatch(src, /-wash\)/);
});

test('features kept', () => {
  assert.match(src, /GoogleLogin/);
  assert.match(src, /filled_black/);
  assert.match(src, /Paper until proven/);
});
