import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('./AiStrategy.jsx', import.meta.url), 'utf8');

test('net is the Hero, only in the row branch', () => {
  assert.match(page, /import Hero from/);
  assert.match(page, /\) : \(\s*<Hero label="Net · paper" value=\{row\.net\}/);
  assert.equal((page.match(/<Hero /g) || []).length, 1);
  assert.doesNotMatch(page, /<Stat label="Net"/);
});

test('Hero children: Open, vs NIFTY, Win rate in a 3-col grid', () => {
  const hero = page.slice(page.indexOf('<Hero'), page.indexOf('</Hero>'));
  assert.match(hero, /grid grid-cols-3/);
  for (const l of ['Open', 'vs NIFTY', 'Win rate']) assert.match(hero, new RegExp(`<Stat label="${l}"`));
});

test('Paper record Card keeps loading, error and empty states', () => {
  assert.match(page, /<Card title="Paper record">[\s\S]*Skeleton[\s\S]*ErrorLine[\s\S]*No trades yet/);
});
