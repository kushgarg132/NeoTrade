import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./SignInCard.jsx', import.meta.url), 'utf8');

test('GoogleButton owns the sign-in call and error display', () => {
  assert.match(src, /export const GoogleButton/);
  assert.match(src, /login\(credentialResponse\.credential\)/);
  assert.match(src, /GoogleLogin/);
  assert.match(src, /filled_black/);
  assert.match(src, /\[color-scheme:light\]/);
  assert.match(src, /role="alert"/);
  assert.match(src, /--loss-soft/);
  assert.doesNotMatch(src, /-wash\)/);
});

test('no navigation inside the card; uses ui Card and beta line', () => {
  assert.doesNotMatch(src, /useNavigate|navigate\(/);
  assert.match(src, /ui\/Card/);
  assert.match(src, /Free while in beta\. Not investment advice\./);
});
