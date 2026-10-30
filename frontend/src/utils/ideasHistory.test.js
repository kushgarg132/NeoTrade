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

test('handled rows: state, when, back date; old rows titled from their id', async () => {
  const { handledSub, handledTitle } = await import('./ideasHistory.js');
  assert.equal(handledSub({ state: 'dismissed', at: '2026-10-30T12:00:00Z' }), 'Dismissed · 30 Oct');
  assert.equal(handledSub({ state: 'snoozed', at: '2026-10-30T12:00:00Z', until: '2026-11-06T12:00:00Z' }), 'Snoozed · 30 Oct · back on 6 Nov');
  assert.equal(handledSub({ state: 'dismissed' }), 'Dismissed');
  assert.equal(handledTitle({ title: 'A hit your stop', action_id: 'x' }), 'A hit your stop');
  assert.equal(handledTitle({ action_id: 'stop_hit:A:90' }), 'A · stop hit');
});
