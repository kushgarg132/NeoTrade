import test from 'node:test';
import assert from 'node:assert/strict';
import { sectionsFor, digestLines } from './todayLayout.js';

test('phase orders', () => {
  assert.deepEqual(sectionsFor('pre'), ['beforeOpen', 'picksTop', 'doToday', 'account', 'markets']);
  assert.deepEqual(sectionsFor('session'), ['doToday', 'account', 'aiActivity', 'markets']);
  assert.deepEqual(sectionsFor('post'), ['afterClose', 'doToday', 'journalPrompt', 'scoreboard', 'account', 'aiActivity']);
  assert.deepEqual(sectionsFor('closed'), ['closedNote', 'doToday', 'afterClose', 'scoreboard', 'account']);
});

test('unknown phase falls back to session', () => {
  assert.deepEqual(sectionsFor(undefined), sectionsFor('session'));
});

test('digest html becomes plain lines', () => {
  assert.deepEqual(digestLines('☀️ <b>Before the open</b>\n• M&amp;M: up'), ['Before the open', '• M&M: up']);
});
