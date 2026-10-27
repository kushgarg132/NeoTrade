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
  let s = run([['reset'], ['cached', { read: { a: 1 }, at: 't', stale: true }], ['stage', { step: 'writing' }], ['delta', { text: 'hi' }]]);
  assert.equal(s.loading, false);
  assert.equal(s.text, 'hi');
  s = aiReducer(s, { symbol: 'X', event: 'report', data: { a: 2 } });
  assert.deepEqual(s.read, { a: 2 });
  assert.equal(s.stale, false);
  assert.equal(s.text, '');
  assert.equal(s.loading, false);
});

test('report takes its at from the frame', () => {
  const s = run([['reset'], ['report', { a: 2, at: 'T1' }]]);
  assert.equal(s.at, 'T1');
  assert.equal(run([['reset'], ['report', { a: 2 }]]).at.length > 10, true);
});

test('stale with no read keeps loading', () => {
  assert.equal(run([['reset'], ['cached', { read: null, stale: true }]]).loading, true);
});

test('error after deltas restores the last read and drops the partial text', () => {
  const s = run([['reset'], ['cached', { read: { a: 1 }, stale: true }], ['delta', { text: 'part' }], ['error', { detail: 'boom' }], ['done']]);
  assert.deepEqual(s.read, { a: 1 });
  assert.equal(s.text, '');
  assert.equal(s.error, 'boom');
  assert.equal(s.streaming, false);
});

test('a frame for another symbol is ignored', () => {
  const s = run([['reset'], ['delta', { text: 'a' }], ['delta', { text: 'b' }, 'Y']]);
  assert.equal(s.text, 'a');
});

test('stage object is stored as-is; error stores the detail string', () => {
  const s = run([['reset'], ['stage', { step: 'news', count: 12 }]]);
  assert.deepEqual(s.stage, { step: 'news', count: 12 });
  assert.equal(run([['reset'], ['error', { detail: 'x' }]]).error, 'x');
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
