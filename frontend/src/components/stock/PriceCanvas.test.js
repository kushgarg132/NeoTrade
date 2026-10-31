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

// color-mix() computes to `color(srgb …)`, which lightweight-charts cannot parse ("Failed to parse color"),
// and the throw left the chart blank. Every colour goes through a canvas pixel to plain rgba().
test('token colours reach the chart as rgba() read back from a canvas pixel', () => {
  const src = read('./PriceCanvas.jsx');
  assert.match(src, /getImageData\(0, 0, 1, 1\)/);
  assert.match(src, /`rgba\(\$\{r\}, \$\{g\}, \$\{b\}, /);
});

// On unmount React runs the mount effect's cleanup (chart.remove()) before the series effect's, and
// removeSeries on a disposed chart threw "Value is undefined", crashing the page (1D -> 1W while loading).
test('series cleanup skips a chart that is already removed', () => {
  assert.match(read('./PriceCanvas.jsx'), /if \(chartRef\.current !== chart\) return;/);
});

// At 1Y on a phone a bar is ~1 px wide, so a tap almost never lands on the news day itself.
test('a tap opens the nearest news dot within NEWS_HIT_PX, not only an exact bar', () => {
  const src = read('./PriceCanvas.jsx');
  assert.match(src, /const NEWS_HIT_PX = 16;/);
  assert.match(src, /timeToCoordinate\(/);
});

// Canvas dots are not focusable: news days are also real buttons under the chart.
test('news days are reachable by keyboard as buttons under the chart', () => {
  const chart = read('./TradingChart.jsx');
  assert.match(chart, /aria-label="News days"/);
  assert.match(chart, /aria-label=\{`\$\{m\.count\} news/);
});

// One failed 60 s poll (yfinance blip, 502) used to replace a working intraday chart with "No price history".
test('a failed intraday poll keeps the rows already on screen', () => {
  assert.match(read('./TradingChart.jsx'), /setLoaded\(\(p\) => \(p\?\.symbol === symbol && p\.days === days \? p : \{ symbol, days, rows: \[\] \}\)\)/);
});
