import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const home = read('./SettingsHome.jsx');
const app = read('../App.jsx');

test('old ?tab= links redirect once, replacing history', () => {
  assert.match(home, /settingsRedirect\(search\)/);
  assert.match(home, /<Navigate replace to=\{old\}/);
});

test('admin lines sit behind isAdmin', () => {
  assert.match(home, /\{isAdmin && <Line parts=\{autopilotLine\(prefs\)\} to="\/settings\/autopilot"/);
  const i = home.indexOf('{isAdmin && (');
  assert.ok(i > 0);
  assert.match(home.slice(i), /to="\/settings\/lab"/);
  assert.equal((home.match(/to="\/settings\/(autopilot|lab)"/g) || []).length, 2);
});

test('Needs you comes first and only when something is broken', () => {
  assert.match(home, /\{needs\.length > 0 && <NeedsYou items=\{needs\} \/>\}\s*<Group title="Your account"/);
});

test('App has the eight settings routes, RequireAdmin on autopilot and lab', () => {
  for (const p of ['brokers', 'guardrails', 'portfolio', 'notifications', 'goal', 'ai', 'autopilot', 'lab']) {
    assert.match(app, new RegExp(`path="/settings/${p}"`), p);
  }
  for (const p of ['autopilot', 'lab']) assert.match(app, new RegExp(`path="/settings/${p}" element=\\{gated\\(<RequireAdmin>`));
  assert.ok(!/path="\/settings\/(profile|brokers|ai)" element=\{gated\(<RequireAdmin>/.test(app));
});

test('deleted settings components are not imported anywhere', () => {
  for (const f of ['./SettingsHome.jsx', '../App.jsx']) assert.doesNotMatch(read(f), /settings\/(Alerts|Theme|Limits)/);
});

test('accounts lead with what connecting does; goal explains its states', () => {
  assert.match(read('../components/settings/Accounts.jsx'), /What connecting does/);
  const goal = read('../components/settings/Goal.jsx');
  assert.match(goal, /Couldn.t load your goal\. Home/);
  assert.match(goal, /No goal set yet/);
  assert.match(goal, /KIND_HELP/);
});

test('Accounts submits a broker return code from its own query, whatever the path', () => {
  const acc = read('../components/settings/Accounts.jsx');
  assert.match(acc, /searchParams\.get\('code'\)/);
  assert.match(acc, /searchParams\.get\('request_token'\)/);
  assert.doesNotMatch(acc, /get\('tab'\)/);
});

test('news alerts live only in Notifications', () => {
  assert.doesNotMatch(read('../components/journal/GuardrailsSheet.jsx'), /news_alerts/);
});

test('Telegram state comes from GET /guardrails (only DELETE exists on /guardrails/telegram)', () => {
  assert.match(home, /api\.get\(endpoints\.guardrails\.status\)[^\n]*res\.data\.telegram/);
});

test('profile: photo in the header, one tap to /profile', () => {
  assert.match(home, /<Link to="\/profile"/);
  assert.match(home, /<PageHeader title="Settings" right=\{profile\} \/>/);
  assert.match(home, /<Avatar src=\{user\?\.picture\}/);
  assert.doesNotMatch(app, /path="\/settings\/profile"/);
});
