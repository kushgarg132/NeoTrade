import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Stock.jsx');
const gauge = read('../components/stock/TechGauge.jsx');
const analysis = read('../components/stock/DetailsTab.jsx');

test('technical gauge uses chartTheme and the Details tab renders it', () => {
  assert.match(gauge, /from '..\/ui\/chartTheme'/);
  assert.match(gauge, /heatColor\(/);
  assert.match(analysis, /<TechGauge/);
});

test('position block is a risk view: avg, qty, P&L, stop distance, private', () => {
  assert.match(page, /Your position · your broker account/);
  assert.match(page, /stopDist/);
  assert.match(page, /if hit/);
  assert.doesNotMatch(page, /No stop set/); // the thesis card is gone (2026-10-28): nowhere to set one
  assert.match(page, /className=\{`private /);
});

test('errors say what failed and offer Retry', () => {
  assert.match(page, /Could not load your position from your broker account/);
  assert.match(analysis, /Could not load the price snapshot[^\n]*onRetry=\{reloadQuick\}/);
});

test('a disabled Buy is explained in words', () => {
  assert.match(page, /Buy is off until a price loads/);
});

test('order flow untouched: Buy and Sell still open the ticket', () => {
  assert.match(page, /side: 'SELL'/);
  assert.match(page, /side: 'BUY'/);
});

test('stop-hit loss shows from-now and vs-cost, both private', () => {
  assert.match(page, /\(stop - price\) \* pos\.qty/);
  assert.match(page, /<span className="private">\{inr\(risk\.stopFromNow[^\n]*from now/);
  assert.match(page, /<span className="private">\(\{inr\(risk\.stopPnl[^\n]*vs what you paid/);
});

// Hide-amounts blurs a `.private` only when it holds no `.private` descendant, so the stop line must
// not wrap its own private spans, and the chart legend must blur the amounts too.
test('stop and target amounts are their own private spans, with no private wrapper', () => {
  const stock = readFileSync(new URL('./Stock.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(stock, /<p className="private">\s*Stop/);
  assert.match(stock, /Stop <span className="private">\{px\(risk\.stop\)\}/);
  assert.match(stock, /target <span className="private">\{px\(risk\.target\)\}/);
  const chart = readFileSync(new URL('../components/stock/TradingChart.jsx', import.meta.url), 'utf8');
  assert.match(chart, /<span className="private">\{l\.amount\}/);
  assert.match(chart, /<PriceCanvas/);
  assert.match(chart, /hidePrices=\{hidden\}/); // the canvas axis cannot blur, so it hides stop/target prices
});

test('the chart reads OHLCV: Stock.jsx passes candles and mine.bars, never closes', () => {
  assert.match(page, /m\?\.bars/);
  assert.match(page, /toBars\(/);
  assert.doesNotMatch(page, /m\?\.closes/);
});

test('price sits on the Hero, not a Card, and stays public', () => {
  assert.match(page, /<Hero[^>]*privateValue=\{false\}/);
  assert.match(page, /format=\{currency === 'INR' \? inr : points\}/);
  assert.match(page, /<DeltaChip[^>]*value=\{currency === 'INR' \? dayAbs : null\}/);
  assert.match(page, /pct=\{dayPct \* 100\}/);
  assert.match(page, /<DeltaChip[\s\S]*?privateValue=\{false\}/);
  assert.match(page, /aria-pressed=\{watching\}/);
  assert.match(page, /<AsOf /);
  assert.match(page, /data-testid="stop-line"/);
  assert.doesNotMatch(page, /text-\[28px\]/);
});

test('the Details tab has no thesis card', () => {
  const details = readFileSync(new URL('../components/stock/DetailsTab.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(details, /ThesisEditor|Your thesis/);
});

test('fundamentals sit under the chart, not in Details', () => {
  assert.match(page, /<TradingChart[\s\S]*?<Fundamentals company=\{company\}/);
  const details = readFileSync(new URL('../components/stock/DetailsTab.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(details, /<Fundamentals/);
});
