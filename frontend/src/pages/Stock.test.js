import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Stock.jsx');
const gauge = read('../components/stock/TechGauge.jsx');
const analysis = read('../components/stock/AnalysisTab.jsx');

test('technical gauge uses chartTheme and the Analysis tab renders it', () => {
  assert.match(gauge, /from '..\/ui\/chartTheme'/);
  assert.match(gauge, /heatColor\(/);
  assert.match(analysis, /<TechGauge/);
});

test('position block is a risk view: avg, qty, P&L, stop distance, private', () => {
  assert.match(page, /Your position · your broker account/);
  assert.match(page, /stopDist/);
  assert.match(page, /if hit/);
  assert.match(page, /No stop set/);
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
