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

test('admin rows sit behind isAdmin', () => {
  const i = home.indexOf('{isAdmin && (');
  assert.ok(i > 0);
  const admin = home.slice(i);
  assert.match(admin, /Autopilot/);
  assert.match(admin, /title="Lab"/);
  assert.ok(!home.slice(0, i).includes('title="Autopilot"'));
});

test('App has the nine settings routes, RequireAdmin on autopilot and lab', () => {
  for (const p of ['profile', 'brokers', 'guardrails', 'portfolio', 'notifications', 'goal', 'ai', 'autopilot', 'lab']) {
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
