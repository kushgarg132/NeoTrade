import test from 'node:test';
import assert from 'node:assert/strict';
import { progress } from './goal.js';

const NOW = new Date('2026-10-19T00:00:00Z').getTime();
const goal = { kind: 'value', target: 200, by: '2027-10-19', start: '2026-04-19', start_value: 100 };
const hist = (v3, v) => ({ points: [{ date: '2026-07-19', value: v3, nifty_value: 1 }, { date: '2026-10-19', value: v, nifty_value: 1 }] });

test('value: share from start_value to target', () => {
  const p = progress(goal, { headline: { value: 150 } }, hist(140, 150), NOW);
  assert.equal(p.pct, 0.5);
});

test('value: pace ahead, on, behind', () => {
  // needs ~2.4%/month from 150 to 200 in 12 months
  assert.equal(progress(goal, { headline: { value: 150 } }, hist(120, 150), NOW).pace, 'ahead');
  assert.equal(progress(goal, { headline: { value: 150 } }, hist(139, 150), NOW).pace, 'on');
  assert.equal(progress(goal, { headline: { value: 150 } }, hist(150, 150), NOW).pace, 'behind');
});

test('value: reached or past, pct clamps to 1 and pace is ahead', () => {
  const p = progress(goal, { headline: { value: 250 } }, hist(240, 250), NOW);
  assert.equal(p.pct, 1);
  assert.equal(p.pace, 'ahead');
});

test('value: below start clamps to 0; missing data does not throw', () => {
  assert.equal(progress(goal, { headline: { value: 80 } }, hist(90, 80), NOW).pct, 0);
  assert.deepEqual(progress(goal, null, null, NOW), { pct: 0, pace: 'on', neededMonthly: null, actualMonthly: null });
  assert.equal(progress(goal, { headline: { value: 150 } }, { points: [] }, NOW).actualMonthly, null);
});

test('value: no start_value falls back to value over target; deadline passed is behind', () => {
  assert.equal(progress({ ...goal, start_value: null }, { headline: { value: 50 } }, null, NOW).pct, 0.25);
  const late = progress({ ...goal, by: '2026-10-01' }, { headline: { value: 150 } }, hist(150, 150), NOW);
  assert.equal(late.pace, 'behind');
});

test('beat_nifty: edge over NIFTY since start against the target points', () => {
  const g = { kind: 'beat_nifty', target: 10, by: '2027-10-19', start: '2026-07-19' };
  const h = { points: [
    { date: '2026-07-19', value: 100, nifty_value: 100 },
    { date: '2026-10-19', value: 110, nifty_value: 105 },
  ] };
  const p = progress(g, null, h, NOW);
  assert.ok(Math.abs(p.pct - ((110 / 105) / 1 - 1) / 0.1) < 1e-9);
  assert.equal(p.pace, 'ahead'); // 1.6%/month edge vs ~0.4% needed
  assert.equal(progress(g, null, { points: [] }, NOW).pct, 0);
});
