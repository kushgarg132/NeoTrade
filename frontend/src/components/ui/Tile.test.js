import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the contract in the source. A tappable Tile shows a chevron and
// pressed/focus states; the plain (non-link) branch gets neither.
const src = readFileSync(new URL('./Tile.jsx', import.meta.url), 'utf8');

test('a Tile with `to` has a chevron, pressed and focus states', () => {
  assert.match(src, /\{to && <ChevronRight/);
  assert.match(src, /active:scale-/);
  assert.match(src, /focus-visible:ring/);
});

test('a plain Tile renders without the link styling', () => {
  assert.match(src, /to \? <Link[^\n]*: <div className=\{cls\}>/);
  assert.doesNotMatch(src.split('const cls')[1].split('\n')[0], /active:|ChevronRight/);
});
