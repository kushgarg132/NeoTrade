import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the contract in the source.
const src = readFileSync(new URL('./Card.jsx', import.meta.url), 'utf8');

test('a card with `to` is one Link with a chevron', () => {
  assert.match(src, /to \?/);
  assert.match(src, /<Link to=\{to\}/);
  assert.match(src, /<ChevronRight/);
});

test('`more` renders its label in a Link to more.to', () => {
  assert.match(src, /<Link to=\{more\.to\}/);
  assert.match(src, /more\.label/);
});

test('docstring says to and more are never both', () => {
  assert.match(src, /never both/);
});
