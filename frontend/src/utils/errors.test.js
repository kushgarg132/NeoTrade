import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detailToText } from './errors.js';

test('a string detail is kept as is', () => {
  assert.equal(detailToText('Daily loss limit hit'), 'Daily loss limit hit');
});

test("a 422 list becomes one readable line naming the field", () => {
  const detail = [{ loc: ['body', 'autopilot_max_trades_per_day'], msg: 'Input should be less than or equal to 100', type: 'less_than_equal' }];
  assert.equal(detailToText(detail), 'Autopilot max trades per day: input should be less than or equal to 100');
});

test('several 422 errors are joined', () => {
  const detail = [
    { loc: ['body', 'quantity'], msg: 'Input should be greater than 0' },
    { loc: ['body', 'limit_price'], msg: 'Field required' },
  ];
  assert.equal(detailToText(detail), 'Quantity: input should be greater than 0 · Limit price: field required');
});

test('anything else is not rendered raw', () => {
  assert.equal(detailToText({ weird: true }), undefined);
  assert.equal(detailToText(undefined), undefined);
});
