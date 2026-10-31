import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./IndexPage.jsx', import.meta.url), 'utf8');

test('level shows on the Hero, not a Stat', () => {
  assert.match(src, /<Hero/);
  assert.match(src, /format=\{points\}/);
  assert.match(src, /privateValue=\{false\}/);
  assert.doesNotMatch(src, /label="Level"/);
});

test('laid out like a stock: Chart (the stock TradingChart, intraday to 5Y), News and Details tabs', () => {
  for (const s of ['52-week high', '52-week low', '50-day average', '200-day average', '1 year', '5 years']) assert.ok(src.includes(s), s);
  assert.match(src, /<TradingChart closes=\{data\.points\} symbol=\{ticker\} currency="pts" intradayUrl=\{endpoints\.marketIndexIntraday\(ticker\)\} newsUrl=\{indexNewsUrl\(ticker\)\} \/>/);
  assert.match(src, /material=true&limit=100/); // market or global material news as chart dots
  assert.match(src, /const TABS = \[\{ id: 'chart'[^\n]*'news'[^\n]*'details'/);
  assert.match(src, /<IndexNews ticker=\{ticker\} \/>/);
  assert.doesNotMatch(src, /CloseLine/);
});

test('why it moved streams over the socket, HTTP only as fallback', () => {
  assert.match(src, /stream\.request\('index_why'/);
  assert.match(src, /m\.event === 'delta'/);
  assert.match(src, /if \(!request\.ok\)/);
});

test('opening shows only the stored explanation; Generate writes one', () => {
  assert.match(src, /params: \{ cached: true \}/);
  assert.match(src, /e\?\.response\?\.status === 404 \? \{ status: 'none' \}/);
  assert.match(src, /Generate explanation/);
  assert.match(src, /run\.ticker === ticker \? run\.n : 0/);
});

test('the explanation sits where a stock AI read does: under the hero, above the tabs', () => {
  const at = ['<Hero label={data.name}', '<Why ticker', '<Tabs tabs={TABS}'].map((x) => src.indexOf(x, src.indexOf('const IndexPage')));
  assert.ok(at.every((i) => i > 0), at.join());
  assert.deepEqual([...at].sort((a, b) => a - b), at);
});
