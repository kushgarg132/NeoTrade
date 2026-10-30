import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// node cannot import .jsx, so the pure helpers live in utils/home.js and TodayCard imports them.
import { todayTitle, briefLines } from '../../utils/home.js';

const src = readFileSync(new URL('./TodayCard.jsx', import.meta.url), 'utf8');

test('title follows the phase', () => {
  assert.equal(todayTitle('premarket'), 'Before the open');
  assert.equal(todayTitle('postclose'), 'After the close');
  assert.equal(todayTitle(null), 'Today');
});

test('brief lines: none without text, AI lines when a summary exists', () => {
  assert.deepEqual(briefLines(undefined, null), { ai: false, lines: [] });
  assert.deepEqual(briefLines('x', { text: 'a\nb\nc' }), { ai: true, lines: ['a', 'b', 'c'] });
});

test('card source contract', () => {
  assert.match(src, /return null/);
  assert.match(src, /noopener,noreferrer/);
  assert.ok(src.includes('to={m.cause?.id ? newsPath(m.cause.id)'));  // the story's analysis
  assert.ok(src.includes('onClick={!m.cause?.id && m.cause?.url ?'));  // else the article
  assert.match(src, /aria-expanded/);
  assert.match(src, /Read all/);
  assert.match(src, /Show less/);
  assert.match(src, /\/market/);
  assert.match(src, /Your money/);
  assert.doesNotMatch(src, /privateValue=\{false\}/);
  assert.match(src, /border-t border-\[var\(--border\)\] pt-3 mt-3/);
});
