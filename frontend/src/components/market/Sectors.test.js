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

test('rows link sectorPath and draw a diverging bar from zero on one scale', () => {
  assert.match(src, /to=\{sectorPath\(s\.sector\)\}/);
  assert.match(src, /<MoveBar value=\{s\.change_pct\} maxAbs=\{maxAbs\} \/>/);
  assert.match(src, /<Breadth b=\{data\.breadth\} \/>/);
});

test('52-week extremes are kept', () => {
  assert.match(src, /near_high/);
  assert.match(src, /near_low/);
});

test('Sectors heading says last session via isClosed()', () => {
  assert.match(src, /isClosed\(\) \? 'Sectors · last session'/);
});

test('filter chips: sectors by All / Rising / Falling / Flagged, extremes by Both / Highs / Lows', () => {
  for (const l of ['All', 'Rising', 'Falling', 'Flagged', 'Both', 'Highs', 'Lows']) assert.match(src, new RegExp(`label: '${l}'`));
  assert.match(src, /filterSectors\(data\.sectors, show\)/);
  assert.match(src, /<ChipRow /);
  assert.match(src, /Nothing matches/);
});
