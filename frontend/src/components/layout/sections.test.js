import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LAB_TABS } from './sections.js';

test('the Autopilot limits tab matches /settings exactly, not as a prefix of Lab pages', () => {
  assert.equal(LAB_TABS.find((t) => t.to === '/settings/autopilot').end, true);
});
