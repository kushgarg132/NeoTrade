import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Today.jsx', import.meta.url), 'utf8');

test('story comes before indices', () => {
  assert.ok(src.indexOf('<Story />') < src.indexOf('<Indices '));
});

test('tile renders without points', () => {
  assert.match(src, /line\.length < 2\) return null/);
});

test('each section has Skeleton, ErrorLine and Empty', () => {
  for (const name of ['Story', 'Indices', 'Scan', 'Events']) {
    const start = src.indexOf(`const ${name} = `);
    const body = src.slice(start, src.indexOf('\nconst ', start + 10));
    assert.match(body, /<Skeleton/, name);
    assert.match(body, /<ErrorLine/, name);
    if (name !== 'Events') assert.match(body, /<Empty/, name); // Events hides itself when empty
  }
});

test('breadth word is shown', () => {
  assert.match(src, /breadthWord\(data\.breadth\)/);
});

test('NIFTY hero on Today, only when ^NSEI row exists', () => {
  assert.match(src, /<Hero to=\{indexPath\('\^NSEI'\)\}/);
  assert.match(src, /label="NIFTY 50"/);
  assert.match(src, /format=\{points\}/);
  assert.match(src, /privateValue=\{false\}/);
  assert.match(src, /nifty && <Hero/);
  assert.match(src, /find\(\(i\) => i\.symbol === '\^NSEI'\)/);
});

test('indices load once, in Today; Indices takes props', () => {
  assert.equal(src.match(/useSection\(loadIndices\)/g).length, 1);
  assert.match(src.slice(src.indexOf('const Today = ')), /useSection\(loadIndices\)/);
  assert.match(src, /const Indices = \(\{ data, error, retry \}\)/);
});

test('TILES drops ^NSEI; tile is 20px and tap', () => {
  assert.match(src, /const TILES = \['\^NSEBANK', '\^BSESN'\]/);
  assert.doesNotMatch(src, /rounded-\[16px\]/);
  assert.match(src, /rounded-\[20px\][^"]*\btap\b|\btap\b[^"]*rounded-\[20px\]/);
});
