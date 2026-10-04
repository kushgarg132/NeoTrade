import { test } from 'node:test';
import assert from 'node:assert/strict';
import { promotionGaps } from './promotion.js';

const ok = (rule) => ({ rule, ok: true, need: 1, have: 1 });

test('passing row has no gaps', () => {
  const row = { backtest_passed: true, backtest: null, paper: { checks: [ok('days'), ok('trades')] } };
  assert.equal(promotionGaps(row), '');
});

test('names a missing backtest and a weak profit factor', () => {
  const row = {
    backtest_passed: false,
    backtest: null,
    paper: { checks: [{ rule: 'profit_factor', ok: false, need: 1.3, have: 1.1 }] },
  };
  assert.equal(promotionGaps(row), 'a passing backtest (none run yet), profit factor 1.3 (now 1.1)');
});

test('null backtest profit factor does not throw', () => {
  const row = {
    backtest_passed: false,
    backtest: { trades: 0, days: 365, profit_factor: null, max_drawdown: 0 },
    paper: { checks: [] },
  };
  assert.equal(promotionGaps(row), 'a passing backtest (last: 0 trades over 365 days, profit factor –)');
});
