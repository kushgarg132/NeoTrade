import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const goal = readFileSync(new URL('./GoalTile.jsx', import.meta.url), 'utf8');
const weekly = readFileSync(new URL('./WeeklyLink.jsx', import.meta.url), 'utf8');

test('goal and weekly links use the 20px radius and tap', () => {
  for (const s of [goal, weekly]) {
    assert.doesNotMatch(s, /rounded-\[16px\]/);
    assert.match(s, /rounded-\[20px\][^"]*\btap\b/);
    assert.doesNotMatch(s, /active:bg-\[var\(--surface-2\)\]/);
  }
});

test('goal and weekly keep their links and copy', () => {
  assert.match(goal, /to="\/settings\/goal"/);
  assert.match(goal, /Set a goal/);
  assert.match(goal, /Home will track it/);
  assert.match(weekly, /showWeekly\(\)/);
  assert.match(weekly, /to="\/reports\/weekly"/);
});
