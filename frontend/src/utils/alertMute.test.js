import { test } from 'node:test';
import assert from 'node:assert/strict';
import { flipMute, undoMute } from './alertMute.js';

test('flipMute merges with the existing mutes', () => {
  assert.deepEqual(flipMute({ ideas: true }, 'news'), { ideas: true, news: true });
  assert.deepEqual(flipMute({ news: true }, 'news'), { news: false });
});

test('undoMute restores only the changed key', () => {
  const now = { ideas: true, news: true, review: true };
  assert.deepEqual(undoMute(now, 'news', false), { ideas: true, news: false, review: true });
});
