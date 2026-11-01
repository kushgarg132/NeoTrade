import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const api = readFileSync(new URL('./api.js', import.meta.url), 'utf8');
const auth = readFileSync(new URL('../context/AuthContext.jsx', import.meta.url), 'utf8');

test('hardLogout dispatches an event instead of redirecting', () => {
  assert.match(api, /export const LOGOUT_EVENT = 'neotrade:logout'/);
  assert.match(api, /dispatchEvent\(new Event\(LOGOUT_EVENT\)\)/);
  assert.doesNotMatch(api, /location\.assign/);
});

test('AuthProvider listens for the logout event', () => {
  assert.match(auth, /addEventListener\(LOGOUT_EVENT/);
  assert.match(auth, /removeEventListener\(LOGOUT_EVENT/);
});
