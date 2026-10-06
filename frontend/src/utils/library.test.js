import { test } from 'node:test';
import assert from 'node:assert/strict';
import { recordLine, statusOf } from './library.js';

const card = (over = {}) => ({
  backtest: { passed: true }, paper: { passed: true }, learned: { paused: false }, stats: { all: null }, ...over,
});

test('status from gates and learning', () => {
  assert.equal(statusOf(card()), 'live-ready');
  assert.equal(statusOf(card({ paper: { passed: false } })), 'paper');
  assert.equal(statusOf(card({ backtest: null })), 'untested');
  assert.equal(statusOf(card({ learned: { paused: true } })), 'paused');
});

test('record line', () => {
  assert.equal(recordLine(card()), 'No paper trades yet');
  assert.equal(recordLine(card({ stats: { all: { trades: 12, win_rate: 0.583, net: 3200 } } })),
    '12 trades · win 58% · net ₹+3,200');
  assert.equal(recordLine(card({ stats: { all: { trades: 1, win_rate: 0, net: -45.6 } } })),
    '1 trade · win 0% · net ₹−46');
});

test('strategy codes read as names', async () => {
  const { strategyName } = await import('./library.js');
  assert.equal(strategyName('orb_breakout'), 'Opening-range breakout');
  assert.equal(strategyName('oversold_rsi_below_lower_band'), 'Oversold rsi below lower band');
  assert.equal(strategyName(undefined), undefined);
});
