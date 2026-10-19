import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitAmounts, splitThesis, oneLine } from './aiText.js';

test('splitAmounts marks rupee amounts and keeps the rest', () => {
  assert.deepEqual(splitAmounts('Up ₹12,340 today, Rs 5 lakh in TCS.'), [
    { text: 'Up ', amount: false }, { text: '₹12,340', amount: true },
    { text: ' today, ', amount: false }, { text: 'Rs 5 lakh', amount: true }, { text: ' in TCS.', amount: false },
  ]);
  assert.deepEqual(splitAmounts('No money here'), [{ text: 'No money here', amount: false }]);
  assert.deepEqual(splitAmounts(undefined), []);
});

test('splitThesis separates the first risk sentence onward', () => {
  const t = splitThesis('Margins are widening. Orders are strong. The main risk is a rupee jump. It could cut export profit.');
  assert.equal(t.why, 'Margins are widening. Orders are strong.');
  assert.equal(t.risk, 'The main risk is a rupee jump. It could cut export profit.');
  assert.deepEqual(splitThesis('Margins are widening. Orders are strong.'), { why: 'Margins are widening. Orders are strong.', risk: '' });
  assert.deepEqual(splitThesis(null), { why: '', risk: '' });
});

test('oneLine takes the first sentence and caps its length', () => {
  assert.equal(oneLine('TCS looks steady. Margins hold.'), 'TCS looks steady.');
  assert.equal(oneLine('x'.repeat(50), 10), 'xxxxxxxxx…');
  assert.equal(oneLine(''), '');
});
