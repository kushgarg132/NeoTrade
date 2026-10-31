import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');

test('PriceCanvas draws with lightweight-charts: candles or area, volume, markers', () => {
  const src = read('./PriceCanvas.jsx');
  assert.match(src, /from 'lightweight-charts'/);
  for (const name of ['createSeriesMarkers', 'CandlestickSeries', 'AreaSeries', 'HistogramSeries']) assert.match(src, new RegExp(name));
  assert.match(src, /LineStyle\.Dashed/);
});

test('PriceCanvas lets the page scroll on phones, cleans up, and follows the theme', () => {
  const src = read('./PriceCanvas.jsx');
  assert.match(src, /vertTouchDrag: false/);
  assert.match(src, /chart\.remove\(\)/);
  assert.match(src, /new MutationObserver/);
});

test('stop/target amounts never reach the canvas axis under hide-amounts', () => {
  assert.match(read('./PriceCanvas.jsx'), /axisLabelVisible: !hidePrices/);
});

test('NewsStrip is a labelled horizontal row of headline cards', () => {
  const src = read('./NewsStrip.jsx');
  assert.match(src, /overflow-x-auto/);
  assert.match(src, /aria-label=\{`News on/);
  assert.match(src, /<NewsLink/);
  assert.match(src, /<ImpactChips/);
});
