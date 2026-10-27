import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Today.jsx', import.meta.url), 'utf8');

test('story comes before indices', () => {
  assert.ok(src.indexOf('<Story />') < src.indexOf('<Indices />'));
});

test('tile renders without points', () => {
  assert.match(src, /points\.length < 2\) return null/);
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
