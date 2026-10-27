import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Header.jsx', import.meta.url), 'utf8');

const read = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
const tabs = read('./BottomTabs.jsx');
const rail = read('./SideRail.jsx');

test('logo is 18px bold on header and rail', () => {
  for (const s of [src, rail]) assert.match(s, /text-\[18px\] font-bold[^"]*">NeoTrade/);
});

test('nav: accent active, muted inactive, surface bar with border, tap links', () => {
  for (const s of [tabs, rail]) {
    assert.match(s, /text-\[var\(--accent\)\]/);
    assert.match(s, /text-\[var\(--text-muted\)\]/);
    assert.match(s, /bg-\[var\(--surface\)\]/);
    assert.match(s, /border-\[var\(--border\)\]/);
    assert.match(s, /'[^']*\btap\b[^']*'/);
  }
});

test('market dot: green only while the socket is live, red otherwise', () => {
  assert.match(src, /const color = feed === 'live' \? 'var\(--gain\)' : 'var\(--loss\)';/);
});
