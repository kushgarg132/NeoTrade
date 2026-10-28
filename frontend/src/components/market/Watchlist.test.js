import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Watchlist.jsx', import.meta.url), 'utf8');

test('non-INR rows print points, not rupees', () => {
  assert.match(src, /s\.currency !== 'INR' \? points : inr/);
});
