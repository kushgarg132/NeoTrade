import { test } from 'node:test';
import assert from 'node:assert/strict';
import { keyNumbers, plainNote, reasonFact } from './verdict.js';

const f = {
  pnl_pct: -31.0, weight_pct: 3.29, nifty_pnl_pct: -8.75, close: 400.85, sma_50: 487.6, sma_200: 522.58,
  below_high_pct: 46.98, return_3m_pct: -18.15, pe: 34.14, debt_to_equity: 0.0332, revenue_growth: 0.814, roe: 0.18,
  quarterly_profit: [3523700000, 4442700000, 1562300000, 1837900000],
};
const limits = { max_loss_pct: 25, max_weight_pct: 20 };

test('each rule shows the figures it fired on', () => {
  assert.equal(reasonFact('loss_beyond_limit', f, limits), 'Down 31.0% from your cost; your limit is 25%');
  assert.equal(reasonFact('below_200dma', f), '₹400.85 against ₹522.58, 23.3% below');
  assert.equal(reasonFact('overweight', f, limits), '3.3% of your portfolio; your limit is 20%');
  assert.equal(reasonFact('high_debt', f), 'Debt/equity 0.03');
  assert.equal(reasonFact('strong_roe', f), 'ROE 18.0%');
  assert.equal(reasonFact('reasonable_valuation', f), 'P/E 34.1');
  assert.equal(reasonFact('earnings_rising_3q', f), 'Quarterly profit ₹184 Cr → ₹156 Cr → ₹444 Cr → ₹352 Cr');
});

test('missing figures or an unknown code give null', () => {
  assert.equal(reasonFact('below_200dma', {}), null);
  assert.equal(reasonFact('loss_beyond_limit', { pnl_pct: -30 }), 'Down 30.0% from your cost');
  assert.equal(reasonFact('nope', f), null);
});

test('key numbers skip what is missing', () => {
  assert.deepEqual(keyNumbers(f).map(([l, v]) => [l, v]), [
    ['From 52-week high', '−47.0%'], ['Last 3 months', '−18.1%'], ['You vs NIFTY', '−31.0% vs −8.8%'],
    ['P/E', '34.1'], ['Debt/equity', '0.03'], ['Revenue growth', '+81.4%'],
  ]);
  assert.deepEqual(keyNumbers({ pe: 12 }).map(([l]) => l), ['P/E']);
});

test('plainNote drops code names', () => {
  assert.equal(plainNote('The `loss_beyond_limit` and `below_200dma` flags'), 'The loss beyond limit and below 200-day average flags');
  assert.equal(plainNote('`earnings_falling_3q` fired'), 'earnings falling 3 quarters fired');
  assert.equal(plainNote(null), '');
});
