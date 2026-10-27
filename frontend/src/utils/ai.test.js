import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scoreboard } from './ai.js';

test('scoreboard formats month AI vs you vs NIFTY and the book stats', () => {
  const s = scoreboard({
    month: { ai: 3200, mine: -1500 }, capital: 100000, mineValue: 500000,
    card: { nifty_return_pct: 1.25, totals: { win_rate: 0.58, trades: 24, costs: 840, max_drawdown: 1200, max_drawdown_pct: 2.4, vs_nifty: -350 } },
  });
  assert.deepEqual(s.versus.map((v) => v.value), ['+3.2%', '-0.3%', '+1.3%']);
  assert.deepEqual(s.versus.map((v) => v.tone), ['gain', 'loss', 'gain']);
  assert.deepEqual(s.stats.map((v) => v.value), ['58%', '24', '₹840', '2.4%', '-₹350']);
  assert.equal(s.stats[3].tone, 'loss');
  assert.equal(s.stats[4].tone, 'loss');
});

test('scoreboard shows dashes when data is missing', () => {
  const s = scoreboard({});
  assert.ok([...s.versus, ...s.stats].every((v) => v.value === '—'));
});
