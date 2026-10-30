import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groupActivity, sources, tally } from './activity.js';

const now = new Date('2026-10-30T12:00:00Z');
const rows = [
  { at: '2026-10-29T03:50:00Z', status: 'REFUSED', source: 'engine', symbol: 'ZYD' },
  { at: '2026-10-30T05:00:00Z', status: 'FILLED', source: 'picks', symbol: 'BEL' },
  { at: '2026-10-30T04:00:00Z', status: 'REFUSED', source: 'engine', symbol: 'GLEN' },
  { at: '2026-10-20T04:00:00Z', status: 'SENT', source: 'news', symbol: 'X' },
];
const shape = (g) => g.map(([d, list]) => [d, list.map((r) => r.symbol)]);

test('grouped by IST day, newest first; oldest flips', () => {
  assert.deepEqual(shape(groupActivity(rows, {}, now)), [['Today', ['BEL', 'GLEN']], ['Yesterday', ['ZYD']], ['20 OCT 2026', ['X']]]);
  assert.deepEqual(shape(groupActivity(rows, { sort: 'oldest' }, now))[0], ['20 OCT 2026', ['X']]);
});

test('filters by status and source', () => {
  assert.deepEqual(shape(groupActivity(rows, { status: 'REFUSED' }, now)), [['Today', ['GLEN']], ['Yesterday', ['ZYD']]]);
  assert.deepEqual(shape(groupActivity(rows, { source: 'picks' }, now)), [['Today', ['BEL']]]);
  assert.deepEqual(groupActivity(rows, { status: 'FILLED', source: 'engine' }, now), []);
});

test('sources present and a day tally', () => {
  assert.deepEqual(sources(rows).map(([v]) => v), ['all', 'engine', 'news', 'picks']);
  assert.equal(tally(rows.slice(0, 3)), '1 filled · 2 refused');
  assert.equal(tally([]), '');
});

import { foldRefusals } from './activity.js';

test('foldRefusals keeps fills in order and names the commonest refusal reason', () => {
  const rows = [{ status: 'REFUSED', reason: 'parked' }, { status: 'FILLED', symbol: 'A' }, { status: 'REFUSED', reason: 'parked' }, { status: 'REFUSED', reason: 'cap' }];
  const f = foldRefusals(rows);
  assert.deepEqual(f.shown.map((r) => r.symbol), ['A']);
  assert.equal(f.refused.length, 3);
  assert.deepEqual([f.reason, f.reasonCount], ['parked', 2]);
  assert.deepEqual(foldRefusals([{ status: 'FILLED' }]).reason, null);
});
