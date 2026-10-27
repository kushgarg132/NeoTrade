import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Header.jsx', import.meta.url), 'utf8');

test('market dot: green only while the socket is live, red otherwise', () => {
  assert.match(src, /const color = feed === 'live' \? 'var\(--gain\)' : 'var\(--loss\)';/);
});
