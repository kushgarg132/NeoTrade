import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AI_EMPTY, aiReducer, splitThesis } from './aiRead.js';
import { stockTab } from './stocks.js';

const run = (frames) => frames.reduce((s, [event, data, symbol = 'X']) => aiReducer(s, { symbol, event, data }), AI_EMPTY);

test('cached fresh read stops loading', () => {
  const s = run([['reset'], ['cached', { read: { a: 1 }, at: 't', stale: false }]]);
  assert.equal(s.loading, false);
  assert.deepEqual(s.read, { a: 1 });
});

test('stale cached read then deltas then report swaps the read', () => {
  let s = run([['reset'], ['cached', { read: { a: 1 }, at: 't', stale: true }], ['stage', 'x'], ['delta', 'hi']]);
  assert.equal(s.loading, false);
  assert.equal(s.text, 'hi');
  s = aiReducer(s, { symbol: 'X', event: 'report', data: { a: 2 } });
  assert.deepEqual(s.read, { a: 2 });
  assert.equal(s.stale, false);
  assert.equal(s.text, '');
});

test('stale with no read keeps loading', () => {
  assert.equal(run([['reset'], ['cached', { read: null, stale: true }]]).loading, true);
});

test('error after deltas restores the last read and drops the partial text', () => {
  const s = run([['reset'], ['cached', { read: { a: 1 }, stale: true }], ['delta', 'part'], ['error', 'boom'], ['done']]);
  assert.deepEqual(s.read, { a: 1 });
  assert.equal(s.text, '');
  assert.equal(s.error, 'boom');
  assert.equal(s.streaming, false);
});

test('a frame for another symbol is ignored', () => {
  const s = run([['reset'], ['delta', 'a'], ['delta', 'b', 'Y']]);
  assert.equal(s.text, 'a');
});

test('splitThesis splits on the marker and hides it', () => {
  assert.deepEqual(splitThesis('A===THESIS===B'), { summary: 'A', thesis: 'B' });
});

test('splitThesis hides a marker cut at a chunk edge', () => {
  assert.equal(splitThesis('A\n===THE').summary, 'A');
  assert.equal(splitThesis('A=').summary, 'A');
  assert.equal(splitThesis('A = B').summary, 'A = B');
});

test('stockTab maps analysis to details', () => {
  assert.equal(stockTab('analysis'), 'details');
  assert.equal(stockTab('news'), 'news');
  assert.equal(stockTab('zzz'), 'chart');
});
