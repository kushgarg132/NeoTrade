import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headline, pct } from './plan.js';

test('pct formats signed percents', () => {
  assert.equal(pct(0.0123), '+1.2%');
  assert.equal(pct(-0.05), '−5.0%');
});

test('headline covers risk-off, trade days and quiet days', () => {
  assert.equal(headline({ risk_off: true }), 'Risk-off: the book sits in cash');
  assert.equal(headline({ buys: [{}], sells: [], holdings: [{}, {}] }), '1 trade today · 2 held');
  assert.equal(headline({ buys: [], sells: [], holdings: [{}] }), 'Holding 1 · no trades today');
});
