import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rankPicks, pickStatus } from './ideas.js';

const p = (id, grade, pUp, med, extra = {}) => ({ id, kind: 'p', grade, pUp, expectedMedian: med, ...extra });

test('rankPicks: engine by score; A before B, then chance up, then expected move; C apart, same order', () => {
  const items = [
    p('b1', 'B', 0.6, 0.05), p('a1', 'A', 0.55, 0.02), p('a2', 'A', 0.58, 0.01), p('a3', 'A', 0.58, 0.03),
    p('c1', 'C', 0.5, 0.01), p('x', null, 0.7, 0.09), p('c2', 'C', 0.52, 0.0),
    { id: 's1', kind: 's', score: { final: 0.6 } }, { id: 's2', kind: 's', score: { final: 0.8 } }, { id: 's3', kind: 's', score: null },
  ];
  const r = rankPicks(items);
  assert.deepEqual(r.engine.map((i) => i.id), ['s2', 's1', 's3']);
  assert.deepEqual(r.ranked.map((i) => i.id), ['a3', 'a2', 'a1', 'b1']);
  assert.deepEqual(r.unproven.map((i) => i.id), ['x', 'c2', 'c1']);
  assert.deepEqual(rankPicks([]), { engine: [], ranked: [], unproven: [] });
});

test('pickStatus: bad news, then results soon, then missed entry, else entry open', () => {
  const base = { kind: 'p', daysSince: 2, firedOn: '2026-10-28', horizon: 20, daysLeft: 18, missedEntry: false };
  const now = Date.parse('2026-10-31T06:00:00Z');
  const bad = { direction: -0.7, impact: 8, published_at: '2026-10-30T05:00:00Z' };
  assert.deepEqual(pickStatus(base, { news: bad, results: '2026-11-05', now }), { label: 'New bad news', kind: 'alert' });
  assert.deepEqual(pickStatus(base, { results: '2026-11-05', now }), { label: 'Results in 5 days', kind: 'unproven' });
  assert.deepEqual(pickStatus({ ...base, missedEntry: true }, { now }), { label: 'Entry missed', kind: 'neutral' });
  assert.deepEqual(pickStatus(base, { now }), { label: 'Entry open', kind: 'proven' });
  // An engine idea has no entry window: only the news and results flags apply.
  assert.equal(pickStatus({ kind: 's', horizon: 5 }, { now }), null);
});
