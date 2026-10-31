import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner: pin the contract in the source.
const news = readFileSync(new URL('./News.jsx', import.meta.url), 'utf8');
const watch = readFileSync(new URL('./Watchlist.jsx', import.meta.url), 'utf8');

test('News uses impact words and the material-today group, not n/10', () => {
  assert.match(news, /import \{ Impact \} from '..\/common\/NewsImpacts'/);
  assert.match(readFileSync(new URL('../common/NewsImpacts.jsx', import.meta.url), 'utf8'), /impactWord\(/);
  assert.match(news, /materialToday\(/);
  assert.doesNotMatch(news, /\/10/);
});

test('Watchlist Empty renders the SmartSearch', () => {
  assert.match(watch, /<Empty[^\n]*<SmartSearch/);
  assert.match(watch, /useSymbolNews/);
  assert.match(watch, /<NewsChip/);
});

test('News: stale replies are dropped; socket refresh merges page 1 and never wipes the list', () => {
  assert.match(news, /mark !== gen\.n/);
  assert.match(news, /mergeFront\(cur, res\.data\.items\)/);
  assert.match(news, /useTopic\('news', \(\) => load\(undefined, true\)\)/);
  assert.match(news, /!refresh\) setError\(true\)/);
});

test('News: lean and material chips, grouped by IST day under the pinned group', () => {
  assert.match(news, /import ChipRow, \{ Chip \} from '..\/ui\/ChipRow'/);
  for (const l of ['Any', 'Bullish', 'Bearish', 'Material only']) assert.match(news, new RegExp(l));
  assert.match(news, /matchLean\(/);
  assert.match(news, /byDay\(/);
  assert.match(news, /material && \{ material: true \}/);
});
