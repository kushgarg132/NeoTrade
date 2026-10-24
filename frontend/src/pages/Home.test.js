import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests: no DOM runner here.
const page = readFileSync(new URL('./Home.jsx', import.meta.url), 'utf8');
const hero = readFileSync(new URL('../components/home/HeroRow.jsx', import.meta.url), 'utf8');

test('hero row: value, today in rupees and percent, versus NIFTY, all private money', () => {
  assert.match(page, /<HeroRow/);
  assert.match(hero, /day_change/);
  assert.match(hero, /NIFTY/);
  assert.match(hero, /private[^\n]*figure-md|figure-md[^\n]*private/);
  assert.match(hero, /your account/i);
});

test('hero empty state names the action and links to accounts', () => {
  assert.match(hero, /<Empty[\s\S]*Connect your broker/);
  assert.match(hero, /settings\?tab=accounts/);
});

test('Needs you is a 44px tappable control, not a body-text link', () => {
  assert.match(page, /to=\{isAdmin \? .\/ideas. : .\/money.\}[^>]*min-h-11/);
  assert.doesNotMatch(page, /<> · <Link/);
});

test('the AI tile carries the Paper label', () => {
  assert.match(page, /title=\{<>AI <Badge kind=\{today\.autopilot\?\.live[^\n]*'Paper'/);
});

test('setup checklist sits above the tiles; one stale banner only', () => {
  assert.ok(page.indexOf('<SetupChecklist') < page.indexOf('<Tile'));
  assert.doesNotMatch(page, /Some figures couldn't refresh/);
});

test('Home: AI tile label follows autopilot.live, Market tile says data is unavailable, hero shows an error', () => {
  assert.match(page, /today\.autopilot\?\.live \? 'live' : 'paper'/);
  assert.doesNotMatch(page, /Open Market/);
  assert.match(page, /failed=\{failed\.money\} onRetry=\{load\}/);
  assert.match(hero, /failed && \(!headline[^\n]*<ErrorLine/);
});

test('a login alert opens the broker login in this tab (an iOS pop-up after await is blocked)', () => {
  const src = readFileSync(new URL('./Home.jsx', import.meta.url), 'utf8');
  const acc = readFileSync(new URL('../components/settings/Accounts.jsx', import.meta.url), 'utf8');
  assert.match(src, /endpoints\.broker\.loginUrl\(a\.login\)/);
  assert.match(src, /window\.location\.assign\(res\.data\.url\)/);
  assert.match(acc, /window\.location\.assign\(res\.data\.url\)/);
  assert.doesNotMatch(acc, /window\.open\(res\.data\.url/);
});
