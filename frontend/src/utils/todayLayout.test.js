import test from 'node:test';
import assert from 'node:assert/strict';
import { digestLines } from './todayLayout.js';

test('digest html becomes plain lines', () => {
  assert.deepEqual(digestLines('☀️ <b>Before the open</b>\n• M&amp;M: up'), ['Before the open', '• M&M: up']);
});
