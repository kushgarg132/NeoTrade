import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gateLine, headline, pct, versusRows, vetoLine } from './plan.js';

test('pct formats signed percents', () => {
  assert.equal(pct(0.0123), '+1.2%');
  assert.equal(pct(-0.05), '−5.0%');
});

test('headline covers risk-off, trade days and quiet days', () => {
  assert.equal(headline({ risk_off: true, nifty_vs_200dma: -0.0244, next_rebalance: '2026-11-09' }),
    'Risk-off: Nifty −2.4% vs its 200-day average, so no buys. Next check 2026-11-09');
  assert.equal(headline({ buys: [{}], sells: [], holdings: [{}, {}] }), '1 trade today · 2 held');
  assert.equal(headline({ buys: [], sells: [], holdings: [{}] }), 'Holding 1 · no trades today');
});

test('scorecard rows, gate and veto lines', () => {
  const card = { book: 0.05, nifty: -0.01, mom30: null, ahead: true, live_ready: false, unlock_on: '2027-02-01' };
  assert.deepEqual(versusRows(card).map((r) => [r.label, r.value, r.tone]), [['AI', '+5.0%', 'gain'], ['NIFTY', '−1.0%', 'loss']]);
  assert.match(gateLine(card), /from 2027-02-01/);
  assert.match(gateLine({ ...card, live_ready: true }), /Live gate met/);
  assert.match(gateLine({ ...card, ahead: false }), /Behind/);
  assert.equal(vetoLine({ n: 0 }), '');
  assert.equal(vetoLine({ n: 2, helped: 1, vetoed_avg: -0.005, book_avg: 0.01 }), '1 of 2 names news kept out did worse than the book (−0.5% vs +1.0%).');
});
