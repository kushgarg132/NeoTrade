import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests: no DOM runner here.
const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = rd('./Ai.jsx');
const board = rd('../components/ai/Scoreboard.jsx');
const pos = rd('../components/ai/Positions.jsx');
const act = rd('../components/ai/Activity.jsx');

test('book header carries the Paper label next to the value and today', () => {
  assert.match(page, /ap\?\.live[\s\S]*Paper/);
  assert.match(page, /AI book/);
});

test('scoreboard cards each carry a Paper chip', () => {
  assert.ok((board.match(/<Paper\b|kind="paper"/g) || []).length >= 3);
});

test('positions: dense rows, Paper label, signed percent, Empty with an action', () => {
  assert.match(pos, /<ListRow[\s\S]*dense/);
  assert.match(pos, /kind="paper"/);
  assert.match(pos, /<Empty[\s\S]*action=/);
});

test('activity: dense rows, Paper label, Empty with an action', () => {
  assert.match(act, /'paper'/);
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
  assert.match(ai, /kind=\{ap\?\.live \? 'live' : 'paper'\}/);
  assert.match(ai, /<ErrorLine message="Couldn't load the autopilot status\." onRetry=\{today\.retry\}/);
});
