import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the contract in the source.
const src = readFileSync(new URL('./ListRow.jsx', import.meta.url), 'utf8');

test('ListRow takes a dense prop, off by default', () => {
  assert.match(src, /dense = false/);
});

test('dense rows are 36 px; the default stays 56 px', () => {
  assert.match(src, /dense \? 'min-h-9 py-1' : 'min-h-14 py-2'/);
});

test('the right value blurs under hide-amounts unless marked public', () => {
  assert.match(src, /privateValue = true/);
  assert.match(src, /\$\{privateValue \? 'private ' : ''\}figure-md/);
});
