import { test } from 'node:test';
import assert from 'node:assert/strict';
import { allowSummary, scoreLine, triggerLabel } from './plan.js';

test('trigger labels', () => {
  assert.equal(triggerLabel('pre_open'), 'Pre-open plan');
  assert.equal(triggerLabel('regime_flip'), 'Regime change');
  assert.equal(triggerLabel('event_passed'), 'Event passed');
  assert.equal(triggerLabel('news:abc'), 'News');
  assert.equal(triggerLabel('fallback'), 'Fallback (AI unavailable)');
  assert.equal(triggerLabel(undefined), '');
});

test('score line sums both sides with signs and Indian grouping', () => {
  const cards = [{ a: { net: 1000 }, b: { net: 400 } }, { a: { net: 240 }, b: { net: -90 } }];
  assert.equal(scoreLine(cards), 'Plan ₹+1,240 vs no plan ₹+310 over 2 days');
  assert.equal(scoreLine([{ a: { net: -1500.4 }, b: { net: 0 } }]), 'Plan ₹−1,500 vs no plan ₹+0 over 1 day');
  assert.equal(scoreLine([]), '');
});

test('allow summary', () => {
  const plan = { allow: [{ symbol: 'TCS', strategies: ['orb_breakout'] }] };
  assert.deepEqual(allowSummary(plan), [{ symbol: 'TCS', strategies: ['orb_breakout'] }]);
  assert.deepEqual(allowSummary(null), []);
});
