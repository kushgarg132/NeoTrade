import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chipLabel, hasRecentNews, sortByNewsRisk, tone } from './news.js';

test('tone follows sentiment, then the headline direction', () => {
  assert.equal(tone({ sentiment: 0.3 }), 'pos');
  assert.equal(tone({ sentiment: -0.25 }), 'neg');
  assert.equal(tone({ sentiment: 0.1 }), 'flat');
  assert.equal(tone({ sentiment: null, direction: -0.6 }), 'neg');
  assert.equal(tone({ sentiment: null, direction: null }), null);
  assert.equal(tone(undefined), null);
});

test('label is signed and never leaks NaN or undefined', () => {
  assert.equal(chipLabel({ sentiment: 0.4 }), 'News +0.4');
  assert.equal(chipLabel({ sentiment: -0.6 }), 'News −0.6');
  assert.equal(chipLabel({ sentiment: null, headline: 'x' }), 'News');
  assert.equal(chipLabel({ sentiment: Number.NaN }), 'News');
});

test('recent news window', () => {
  const now = Date.parse('2026-10-06T10:00:00Z');
  assert.equal(hasRecentNews({ published_at: '2026-10-06T00:00:00Z' }, 24, now), true);
  assert.equal(hasRecentNews({ published_at: '2026-10-04T00:00:00Z' }, 24, now), false);
  assert.equal(hasRecentNews({ published_at: null }, 24, now), false);
  assert.equal(hasRecentNews(undefined, 24, now), false);
});

test('material bad news sorts first, otherwise order is kept', () => {
  const rows = [{ symbol: 'A' }, { symbol: 'B' }, { symbol: 'C' }, { symbol: 'D' }];
  const news = { C: { material: true, direction: -0.7 }, B: { material: true, direction: 0.8 }, D: { material: true, direction: -0.5 } };
  assert.deepEqual(sortByNewsRisk(rows, news).map((r) => r.symbol), ['C', 'D', 'A', 'B']);
  assert.deepEqual(sortByNewsRisk(rows, {}).map((r) => r.symbol), ['A', 'B', 'C', 'D']);
});
