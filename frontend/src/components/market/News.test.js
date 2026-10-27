import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner: pin the contract in the source.
const news = readFileSync(new URL('./News.jsx', import.meta.url), 'utf8');
const watch = readFileSync(new URL('./Watchlist.jsx', import.meta.url), 'utf8');

test('News uses impact words and the material-today group, not n/10', () => {
  assert.match(news, /impactWord\(/);
  assert.match(news, /materialToday\(/);
  assert.doesNotMatch(news, /\/10/);
});

test('Watchlist Empty renders the SmartSearch', () => {
  assert.match(watch, /<Empty[^\n]*<SmartSearch/);
  assert.match(watch, /useSymbolNews/);
  assert.match(watch, /<NewsChip/);
});
