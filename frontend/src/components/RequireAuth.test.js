import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./RequireAuth.jsx', import.meta.url), 'utf8');

test('signed out shows the sign-in card inside the shell, never a redirect', () => {
  assert.match(src, /SignInCard/);
  assert.match(src, /<Layout>/);
  assert.doesNotMatch(src, /Navigate/);
});
