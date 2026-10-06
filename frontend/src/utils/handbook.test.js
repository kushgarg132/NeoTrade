import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitLive } from './handbook.js';

const known = ['jobs', 'news'];

test('no markers: one text part', () => {
  assert.deepEqual(splitLive('# Title\nbody', known), [{ md: '# Title\nbody' }]);
});

test('a marker splits the text around a live panel', () => {
  assert.deepEqual(splitLive('a\n<!-- live:jobs -->\nb', known), [{ md: 'a\n' }, { live: 'jobs' }, { md: '\nb' }]);
});

test('an unknown panel is dropped, its text kept', () => {
  assert.deepEqual(splitLive('a\n<!-- live:foo -->\nb', known), [{ md: 'a\n\nb' }]);
});

test('markers at the edges leave no empty text parts', () => {
  assert.deepEqual(splitLive('<!-- live:jobs -->\nx\n<!-- live:news -->', known),
    [{ live: 'jobs' }, { md: '\nx\n' }, { live: 'news' }]);
});
