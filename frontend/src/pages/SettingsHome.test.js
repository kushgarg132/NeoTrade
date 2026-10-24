import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const home = read('./SettingsHome.jsx');

test('every tab has a plain-words line saying what it is for', () => {
  assert.match(home, /TAB_HELP/);
  for (const id of ['accounts', 'alerts', 'limits', 'profile', 'theme', 'goal', 'lab']) assert.match(home, new RegExp(`${id}:`));
});

test('accounts lead with what connecting does, as short lines', () => {
  assert.match(read('../components/settings/Accounts.jsx'), /What connecting does/);
});

test('errors say what is affected and Retry stays', () => {
  const alerts = read('../components/settings/Alerts.jsx');
  assert.match(alerts, /Couldn.t load Telegram/);
  assert.match(alerts, /onRetry/);
  assert.match(read('../components/settings/Goal.jsx'), /Couldn.t load your goal\. Home/);
});

test('goal explains both goal types and the empty state', () => {
  const goal = read('../components/settings/Goal.jsx');
  assert.match(goal, /No goal set yet/);
  assert.match(goal, /KIND_HELP/);
});

test('theme says what it changes', () => {
  assert.match(read('../components/settings/Theme.jsx'), /every screen/);
});

test('admin gate and legacy redirects are kept', () => {
  assert.match(home, /isAdmin \? \[\{ id: 'lab'/);
  assert.match(home, /LEGACY/);
});
