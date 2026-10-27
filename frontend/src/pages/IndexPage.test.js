import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./IndexPage.jsx', import.meta.url), 'utf8');

test('level shows on the Hero, not a Stat', () => {
  assert.match(src, /<Hero/);
  assert.match(src, /format=\{points\}/);
  assert.match(src, /privateValue=\{false\}/);
  assert.doesNotMatch(src, /label="Level"/);
});

test('other stats and the close line stay', () => {
  for (const s of ['52-week range', '50-day average', '200-day average', '<CloseLine']) assert.ok(src.includes(s), s);
});
