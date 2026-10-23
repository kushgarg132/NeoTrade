import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract pins for the Money redesign (no DOM runner in this repo).
const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Money.jsx');
const holdings = read('../components/money/HoldingsTab.jsx');
const overview = read('../components/money/OverviewTab.jsx');
const chart = read('../components/money/ValueChart.jsx');

test('empty account offers both Connect your broker and Import files in one Empty', () => {
  const empty = page.split('<Empty')[1].split('/>')[0];
  assert.match(empty, /Connect your broker/);
  assert.match(empty, /Import files/);
  assert.match(empty, /\/settings\?tab=accounts/);
});

test('holdings with no rows also offers both actions', () => {
  assert.match(holdings, /Connect your broker/);
});

test('stale holdings show a warning badge above the figure', () => {
  const stale = page.indexOf('holdingsStale(');
  assert.ok(stale > 0 && stale < page.indexOf('figure-lg'));
  assert.match(page, /Badge kind="unproven"/);
});

test('page says these are your own broker figures', () => {
  assert.match(page, /Your broker account/);
});

test('headline carries total P&L, private', () => {
  assert.match(page, /Total P&L/);
  assert.match(page, /private[^\n]*h\.pnl|Stat[^\n]*Total P&L/);
});

test('holdings rows are dense: LTP, today %, P&L and weight columns, no filler', () => {
  assert.match(holdings, /grid-cols-\[/);
  assert.match(holdings, /h\.last_price/);
  assert.match(holdings, /h\.pnl\b/);
  assert.match(holdings, /MARKET_WHY/);
  assert.doesNotMatch(holdings, /min-h-16/);
  assert.match(holdings, /className="private">\s*<Cell\s+top=\{h\.pnl/);
});

test('overview does not stack empties when there is no headline, and drops the duplicate P&L card', () => {
  assert.match(overview, /if \(!headline\) return null/);
  assert.doesNotMatch(overview, /label="Put in"/);
});

test('value chart uses chartTheme', () => {
  assert.match(chart, /chartTheme/);
});
