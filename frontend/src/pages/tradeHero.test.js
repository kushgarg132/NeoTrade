import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const rt = readFileSync(new URL('./RoundTrip.jsx', import.meta.url), 'utf8');
const ai = readFileSync(new URL('./AiTrade.jsx', import.meta.url), 'utf8');

test('RoundTrip puts closed P&L on the Hero; open keeps the Stat', () => {
  assert.match(rt, /import Hero from/);
  assert.match(rt, /!open && <Hero label="P&L"/);
  assert.match(rt, /format=\{\(v\) => inr\(v, \{ sign: true \}\)\}/);
  assert.match(rt, /open && <div className="private"><Stat label="P&L" value="Open"/);
  assert.match(rt, /<div className="private"><Stat label="Average entry"/);
  assert.match(rt, /<div className="private"><Stat label="Average exit"/);
  assert.match(rt, /View stock/);
  assert.match(rt, /<NewsChips/);
  assert.doesNotMatch(rt, /privateValue=\{false\}/);
});

test('AiTrade puts closed net on the Hero', () => {
  assert.match(ai, /import Hero from/);
  assert.match(ai, /!s\.open && <Hero label="Net"/);
  assert.doesNotMatch(ai, /<Stat label="Net"/);
  for (const k of ['label="Gross"', 'label="Costs"', 'label="Exit reason"', 'Open {t.symbol}']) assert.ok(ai.includes(k), k);
  assert.doesNotMatch(ai, /privateValue=\{false\}/);
});
