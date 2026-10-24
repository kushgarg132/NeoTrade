import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./IdeasHistory.jsx', import.meta.url), 'utf8');

test('every section carries the Paper label and a plain note', () => {
  assert.match(src, /<Badge kind="paper">Paper<\/Badge>/);
  assert.match(src, /Net = after costs/);
});

test('each row says beat or lagged, not colour alone', () => {
  assert.match(src, /'Beat' : 'Lagged'/);
});

test('a summary line counts scored, up and beat NIFTY', () => {
  assert.match(src, /scored · /);
  assert.match(src, /beat NIFTY/);
});

test('empty sections name the action and strategy names are readable', () => {
  assert.match(src, /<Empty title=\{empty\}[^>]*action=/);
  assert.match(src, /See open ideas/);
  assert.match(src, /nice\(r\.name\)/);
});

test('admin gate and Retry stay', () => {
  assert.match(src, /role === 'admin'/);
  assert.match(src, /onRetry=\{state\.reload\}/);
});
