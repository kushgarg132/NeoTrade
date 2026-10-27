import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract checks for the Sectors tab (no DOM runner here).
const src = readFileSync(new URL('./Sectors.jsx', import.meta.url), 'utf8');

test('sort control has Move, News and Breadth, defaulting to Move', () => {
  for (const l of ['Move', 'News', 'Breadth']) assert.match(src, new RegExp(`label: '${l}'`));
  assert.match(src, /useState\('move'\)/);
  assert.match(src, /sortSectors\(/);
});

test('no newsFeed read: sentiment comes from the scan', () => {
  assert.doesNotMatch(src, /newsFeed/);
  assert.match(src, /marketScan/);
});

test('cells link sectorPath and use heatColor', () => {
  assert.match(src, /to=\{sectorPath\(s\.sector\)\}/);
  assert.match(src, /heatColor\(s\.change_pct/);
});

test('52-week extremes are kept', () => {
  assert.match(src, /near_high/);
  assert.match(src, /near_low/);
});
