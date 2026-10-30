import { test } from 'node:test';
import assert from 'node:assert/strict';
import { firstDue, waiting } from './ideasHistory.js';

test('unscored picks and records, soonest first, with days left', () => {
  const picks = [{ _id: 'a', symbol: 'BHEL', label: 'Momentum', due_date: '2026-11-03', outcome: null },
    { _id: 'b', symbol: 'DABUR', due_date: '2026-10-20', outcome: { net: 0.01 } }];
  const records = [{ id: 'r1', symbol: 'NLCINDIA', side: 'BUY', due_date: '2026-11-02', outcome: null }];
  const w = waiting(picks, records, '2026-10-30');
  assert.deepEqual(w.map((x) => [x.symbol, x.kind, x.days]), [['NLCINDIA', 'Forward', 3], ['BHEL', 'Pick', 4]]);
  assert.equal(firstDue(w), '2026-11-02');
  assert.equal(firstDue([]), null);
});
