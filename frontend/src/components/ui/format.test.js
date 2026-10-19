import { test } from 'node:test';
import assert from 'node:assert/strict';
import { inr, pct, tone, compactInr } from './format.js';

test('inr groups the Indian way', () => {
  assert.equal(inr(409205), '₹4,09,205');
  assert.equal(inr(-1500, { sign: true }), '-₹1,500');
  assert.equal(inr(1500, { sign: true }), '+₹1,500');
  assert.equal(inr(null), '—');
});

test('compactInr uses L and Cr', () => {
  assert.equal(compactInr(409205), '₹4.09L');
  assert.equal(compactInr(12000000), '₹1.2Cr');
  assert.equal(compactInr(8500), '₹8,500');
});

test('pct and tone', () => {
  assert.equal(pct(0.0165, { sign: true }), '+1.65%');
  assert.equal(pct(-0.02), '-2.00%');
  assert.equal(pct(0.1, { dp: 0 }), '10%');
  assert.equal(tone(-1), 'loss');
  assert.equal(tone(2), 'gain');
  assert.equal(tone(0), 'neutral');
});
