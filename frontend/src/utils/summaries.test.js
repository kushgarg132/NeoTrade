import { test } from 'node:test';
import assert from 'node:assert/strict';
import { amountParts, summaryLines } from './summaries.js';

test('amountParts marks rupee amounts and nothing else', () => {
  const parts = amountParts('You hold ₹2,950, down −₹50 (1.7%) after 3 days.');
  assert.deepEqual(parts.filter((p) => p.amount).map((p) => p.text), ['₹2,950', '−₹50']);
  assert.equal(parts.map((p) => p.text).join(''), 'You hold ₹2,950, down −₹50 (1.7%) after 3 days.');
});

test('amountParts keeps crore and lakh units with the amount', () => {
  assert.deepEqual(amountParts('FII net ₹1,200 cr today').filter((p) => p.amount).map((p) => p.text), ['₹1,200 cr']);
  assert.deepEqual(amountParts('no money here'), [{ text: 'no money here', amount: false }]);
  assert.deepEqual(amountParts(null), []);
});

test('summaryLines drops blanks', () => {
  assert.deepEqual(summaryLines('a\n\n  b \n'), ['a', 'b']);
  assert.deepEqual(summaryLines(undefined), []);
});

test('amountParts handles an amount at the very start', () => {
  assert.deepEqual(amountParts('₹500 gained'), [{ text: '₹500', amount: true }, { text: ' gained', amount: false }]);
});
