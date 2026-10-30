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
  assert.match(readFileSync(new URL('../components/ui/Hero.jsx', import.meta.url), 'utf8'), /private[^\n]*figure-md|figure-md[^\n]*private/);
  assert.match(hero, /your account/i);
});

test('hero empty state names the action and links to accounts', () => {
  assert.match(hero, /<Empty[\s\S]*Connect your broker/);
  assert.match(hero, /settings\/brokers/);
});

const needs = readFileSync(new URL('../components/home/NeedsYou.jsx', import.meta.url), 'utf8');

test('Needs you shows the top stocks inline with their action, ideas waiting and See all', () => {
  assert.match(page, /<NeedsYou need=\{need\} isAdmin=\{isAdmin\}/);
  assert.match(needs, /triageHoldings\(need\.actions\)/); // the Ideas tab's own order
  assert.match(needs, /<OrderTicket \{\.\.\.ticket\}/);
  assert.match(needs, /const all = isAdmin \? '\/ideas\?tab=holdings' : '\/money'/);
  assert.match(needs, /See all/);
  assert.match(needs, /You're clear\./);
});

test('the AI row carries the Paper label', () => {
  assert.match(page, /AI account <Badge kind=\{today\.autopilot\?\.live \? 'live' : 'paper'\}>/);
});

test('setup checklist sits above Needs you; one stale banner only', () => {
  assert.ok(page.indexOf('<SetupChecklist') < page.indexOf('<NeedsYou'));
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

test('every unfinished setup step can be skipped, saved to the account, and undone', () => {
  const setup = readFileSync(new URL('../components/home/SetupChecklist.jsx', import.meta.url), 'utf8');
  assert.match(setup, /setup_skipped: next/);
  assert.match(setup, /endpoints\.settings\.preferences/);
  assert.match(setup, /\{!s\.done && \(/);
  assert.match(setup, /'Undo' : 'Skip'/);
  assert.match(setup, /min-h-11 min-w-11/);
});

test('Home order: status and alerts, hero with the goal, setup, needs you, today card, AI and indices, weekly', () => {
  const at = ['phaseLabel(today.phase)', 'alerts(today)', '<HeroRow', '<GoalTile compact', '<SetupChecklist', '<NeedsYou', '<TodayCard', 'AI account', 'r.percent', '<WeeklyLink'].map((s) => page.indexOf(s));
  assert.ok(at.every((i) => i >= 0), at.join());
  assert.deepEqual([...at].sort((a, b) => a - b), at);
  assert.doesNotMatch(page, /NewsMoves|BriefCard/);
});

test('alerts: tap, soft loss fill, role and login kept', () => {
  assert.match(page, /role="alert"/);
  assert.match(page, /openBrokerLogin/);
  assert.match(page, /var\(--loss-soft\)/);
  assert.doesNotMatch(page, /border-\[var\(--loss\)\]/);
  assert.match(page, /text-\[var\(--loss\)\] tap/);
});

test('the Today card draws once its three sources are in, not swapped a second later', () => {
  assert.match(page, /useState\(undefined\); \/\/ undefined until the AI day summary has answered/);
  assert.match(page, /day !== undefined && \(overview \|\| failed\.money\)/);
  assert.match(page, /setDay\(\(d\) => d \?\? null\)/); // a failed summary still lets the digest show
});
