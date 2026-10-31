import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./Header.jsx', import.meta.url), 'utf8');

const read = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
const tabs = read('./BottomTabs.jsx');
const rail = read('./SideRail.jsx');

test('header and rail show the shared Logo; mark stays emerald, wordmark 18px bold', () => {
  for (const s of [src, rail]) assert.match(s, /<Logo \/>/);
  const logo = read('./Logo.jsx');
  assert.match(logo, /text-\[18px\] font-bold/);
  assert.match(logo, /fill="#10b981"/);
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

test('market dot: green only while the socket is live, amber otherwise', () => {
  assert.match(src, /const color = feed === 'live' \? 'var\(--gain\)' : 'var\(--warn\)';/);
});
