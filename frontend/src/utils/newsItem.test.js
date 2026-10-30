import { test } from 'node:test';
import assert from 'node:assert/strict';
import { targetCalls, sourceName } from './newsItem.js';

test('targetCalls joins each call to its outcome and judges it at the longest measured horizon', () => {
  const item = {
    impacts: [{ type: 'symbol', target: 'INFY', direction: 0.5, impact: 5 }, { type: 'symbol', target: 'JSW', direction: 0.8, impact: 7 },
      { type: 'market', target: 'INDIA', direction: 0.5, impact: 6 }, { type: 'sector', target: 'IT', direction: -0.4, impact: 3 }],
    outcomes: [
      { type: 'symbol', target: 'INFY', ret_1d: 0, bench_1d: 0, ret_5d: -0.0266, bench_5d: 0.0043 },
      { type: 'symbol', target: 'JSW', ret_1d: 0, bench_1d: 0, ret_5d: 0.047, bench_5d: 0.0044 },
      { type: 'market', target: 'INDIA', ret_5d: 0.0012, bench_5d: 0.0012 },
    ],
  };
  const c = Object.fromEntries(targetCalls(item).map((x) => [x.target, x]));
  assert.deepEqual(targetCalls(item).map((x) => x.target), ['JSW', 'INDIA', 'INFY', 'IT']); // strongest call first
  assert.equal(c.JSW.verdict, 'right');
  assert.equal(c.INFY.verdict, 'wrong');
  assert.equal(c.INFY.at, '5d');
  assert.equal(c.INDIA.verdict, 'flat'); // the market judged on its own move, here +0.12%
  assert.equal(c.IT.verdict, 'pending');
  assert.equal(c.JSW.moves[0].move, null); // 1h not measured
});

test('sourceName names the feed ids and leaves real names alone', () => {
  assert.equal(sourceName('hbl_markets'), 'BusinessLine');
  assert.equal(sourceName('et_economy'), 'Economic Times');
  assert.equal(sourceName('India Infoline'), 'India Infoline');
  assert.equal(sourceName(undefined), undefined);
});
