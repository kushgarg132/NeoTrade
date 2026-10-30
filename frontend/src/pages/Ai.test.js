import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests: no DOM runner here.
const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = rd('./Ai.jsx');
const board = rd('../components/ai/Scoreboard.jsx');
const pos = rd('../components/ai/Positions.jsx');
const act = rd('../components/ai/Activity.jsx');

test('book header says Paper or Live once, with the autopilot state, under the value and today', () => {
  assert.match(page, /\{ap\.live \? 'Live' : 'Paper'\} · Autopilot \{on \? 'on' : 'off'\}/);
  assert.match(page, /AI book/);
});

test('scoreboard: this month as bars on one scale; no Paper chip repeated per card', () => {
  assert.match(board, /<Versus rows=\{s\.versus\} \/>/);
  assert.doesNotMatch(board, /<Paper\b|kind="paper"/);
});

test('positions: dense rows, Paper label, signed percent, Empty with an action', () => {
  assert.match(pos, /<ListRow[\s\S]*dense/);
  assert.match(pos, /kind="paper"/);
  assert.match(pos, /<Empty[\s\S]*action=/);
});

test('activity: one-line rows, Live flagged per row, refusals folded per day, Empty with an action', () => {
  assert.match(act, /\{live && <span[^\n]*<Badge kind="live">Live<\/Badge>/);
  assert.match(act, /foldRefusals\(list\)/);
  assert.match(act, /fold=\{status === 'all'\}/); // the Refused filter shows them unfolded
  assert.match(act, /<Empty[\s\S]*action=/);
});

test('scoreboard Empty states name an action; errors name what failed', () => {
  assert.ok((board.match(/<Empty[^>]*action=/g) || []).length >= 2);
  assert.match(board, /Couldn.t load the AI/);
});

test('Paper or Live comes from the data: per Activity row, and the book badge defaults to Paper with a Retry', () => {
  const act = rd('../components/ai/Activity.jsx');
  assert.doesNotMatch(act, /title="Last 30" action=/);
  assert.match(act, /r\.mode\)\.toUpperCase\(\) === 'LIVE'/);
  const ai = rd('./Ai.jsx');
  assert.match(ai, /<ErrorLine message="Couldn't load the autopilot status\." onRetry=\{today\.retry\}/);
});

test('book header says when the Lab is off and which strategies are paused', () => {
  assert.match(page, /ap\.lab === false[\s\S]*Lab off/);
  assert.match(page, /ap\.paused\?\.length > 0[\s\S]*Paused on paper/);
});

test('book header is the Hero with a today chip; null-safe percent', () => {
  assert.match(page, /import Hero from/);
  assert.match(page, /import DeltaChip from/);
  assert.match(page, /<Hero label="AI book"/);
  assert.match(page, /typeof dayPct === 'number' \? dayPct \* 100 : undefined/);
  assert.match(page, /suffix="today"/);
  assert.doesNotMatch(page, /rounded-\[16px\]/);
  assert.match(page, /<Card><Skeleton rows=\{2\} \/><\/Card>/);
  for (const s of ['Autopilot {on ?', 'cap deployed', 'Lab off', 'Paused on paper', '<StopAi compact', '/settings/autopilot', 'role="progressbar"']) assert.ok(page.includes(s), s);
});

test('accent buttons use accent-ink, not surface', () => {
  for (const src of [board, pos, act]) {
    assert.doesNotMatch(src, /bg-\[var\(--accent\)\][^"]*text-\[var\(--surface\)\]/);
    assert.match(src, /text-\[var\(--accent-ink\)\]/);
  }
});
