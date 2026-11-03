import { test } from 'node:test';
import assert from 'node:assert/strict';
import { badNewsSince, chipLabel, hasNews, lossCause, mergeFront, newsToday, resultsFlag, tone } from './news.js';

test('newsToday is a material item on the IST day; hasNews needs a headline', () => {
  const now = Date.parse('2026-10-26T10:00:00Z'); // 15:30 IST
  assert.equal(newsToday({ material: true, published_at: '2026-10-25T19:00:00Z' }, now), true); // 00:30 IST on the 26th
  assert.equal(newsToday({ material: true, published_at: '2026-10-25T18:00:00Z' }, now), false);
  assert.equal(newsToday({ material: false, published_at: '2026-10-26T09:00:00Z' }, now), false);
  assert.equal(newsToday({ material: true, published_at: null }, now), false);
  assert.equal(hasNews({ headline: 'x' }), true);
  assert.equal(hasNews({ sentiment: 0.3, headline: null }), false);
});

test('badNewsSince needs a strong negative item after the fire day', () => {
  const bad = { direction: -0.6, impact: 8, published_at: '2026-10-24T05:00:00Z' };
  assert.equal(badNewsSince(bad, '2026-10-23'), true);
  assert.equal(badNewsSince(bad, '2026-10-24'), false);
  assert.equal(badNewsSince({ ...bad, impact: 6 }, '2026-10-23'), false);
  assert.equal(badNewsSince({ ...bad, direction: -0.4 }, '2026-10-23'), false);
  assert.equal(badNewsSince(bad, null), false);
  assert.equal(badNewsSince(undefined, '2026-10-23'), false);
});

test('resultsFlag only inside the horizon', () => {
  const now = Date.parse('2026-10-26T06:00:00Z');
  assert.equal(resultsFlag('2026-11-01', 5, now), 'Results in 6 days');
  assert.equal(resultsFlag('2026-10-27', 5, now), 'Results in 1 day');
  assert.equal(resultsFlag('2026-10-26', 5, now), 'Results today');
  assert.equal(resultsFlag('2026-11-03', 5, now), null); // 8 days > 7 calendar days
  assert.equal(resultsFlag('2026-10-20', 5, now), null);
  assert.equal(resultsFlag(null, 5, now), null);
  assert.equal(resultsFlag('2026-10-27', null, now), null);
});

test('lossCause names the news behind a drop', () => {
  assert.deepEqual(lossCause({ material: true, direction: -0.7, headline: 'Q2 miss' }), { news: true, text: 'Drop after news: Q2 miss' });
  assert.deepEqual(lossCause({ material: false, direction: -0.7, headline: 'x' }), { news: false, text: 'Slow decline' });
  assert.deepEqual(lossCause(undefined), { news: false, text: 'Slow decline' });
});

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

test('mergeFront puts the fresh page first and keeps older paged items', () => {
  const cur = [{ id: 'b' }, { id: 'c' }, { id: 'd' }];
  const fresh = [{ id: 'a' }, { id: 'b' }];
  assert.deepEqual(mergeFront(cur, fresh).map((n) => n.id), ['a', 'b', 'c', 'd']);
  assert.deepEqual(mergeFront(null, fresh).map((n) => n.id), ['a', 'b']);
});
