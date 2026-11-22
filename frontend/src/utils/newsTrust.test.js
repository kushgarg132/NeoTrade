import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lean, newsTrust, setNewsTrust } from './newsTrust.js';
import { badNewsSince, lossCause, matchLean, tone } from './news.js';
import { filters, groupNews } from '../components/stock/newsGroups.js';

const bad = { material: true, direction: -0.8, impact: 8, headline: 'Guidance cut', published_at: '2026-11-20T05:00:00Z' };

test('until /news/trust says otherwise, no view gets a direction', () => {
  assert.equal(newsTrust().trusted, false); // unknown = hidden
  assert.equal(lean(-0.8), 0);
  assert.equal(tone(bad), null);
  assert.equal(lossCause(bad).news, false);
  assert.equal(badNewsSince(bad, '2026-11-19'), false);
  assert.equal(matchLean({ impacts: [{ direction: 0.9, impact: 8 }] }, 'up'), false);
  assert.deepEqual(filters().map(([id]) => id), ['all', 'material']);
  assert.deepEqual(groupNews([{ title: 'x', direction: -1, at: bad.published_at }], 'down', 'newest'), []);
});

test('a trusted scorer shows its calls again; sentiment shows either way', () => {
  assert.equal(tone({ sentiment: 0.5 }), 'pos');
  setNewsTrust({ trusted: true, line: 'right 55% of 400' });
  assert.equal(lean(-0.8), -1);
  assert.equal(tone(bad), 'neg');
  assert.equal(lossCause(bad).news, true);
  assert.deepEqual(filters().map(([id]) => id), ['all', 'up', 'down', 'material']);
  setNewsTrust(null);
  assert.equal(newsTrust().trusted, false);
});
