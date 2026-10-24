import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests: the handbook page and its live panels (no DOM runner here).
const page = readFileSync(new URL('./Handbook.jsx', import.meta.url), 'utf8');
const panels = readFileSync(new URL('../components/system/LivePanels.jsx', import.meta.url), 'utf8');
const tabs = readFileSync(new URL('../components/system/SystemTabs.jsx', import.meta.url), 'utf8');

test('page has a title, a plain gloss and an on-this-page outline', () => {
  assert.match(page, /<PageHeader title="Handbook"/);
  assert.match(page, /On this page/);
});

test('status failure is retryable and panels show a skeleton while loading', () => {
  assert.match(page, /onRetry=\{load\}|onRetry=\{reload\}/);
  assert.match(panels, /<Skeleton/);
  assert.match(panels, /<ErrorLine[^>]*onRetry/);
});

test('live panels and tabs use the ui kit, not the old Sheet/Statement kit', () => {
  assert.doesNotMatch(panels, /doc\/Doc/);
  assert.doesNotMatch(tabs, /doc\/Doc/);
  assert.match(panels, /ui\/Card/);
  assert.match(tabs, /ui\/Tabs/);
});

test('reading column: tables scroll inside themselves and headings are plain sans', () => {
  assert.match(page, /\[&_table\]:overflow-x-auto/);
  assert.match(page, /\[&_h2\]:text-\[18px\]/);
});
