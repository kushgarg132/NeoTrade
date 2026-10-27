import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

const src = (n) => readFileSync(new URL(`./${n}.jsx`, import.meta.url), 'utf8');

test('Card is a 20 px surface and pressable when it links', () => {
  assert.match(src('Card'), /rounded-\[20px\]/);
  assert.match(src('Card'), /\btap\b/);
});

test('primary Button is accent fill with accent ink, 44 px, 12 px radius, tap', () => {
  const s = src('Button');
  assert.match(s, /bg-\[var\(--accent\)\]/);
  assert.match(s, /text-\[var\(--accent-ink\)\]/);
  assert.match(s, /min-h-11/);
  assert.match(s, /rounded-\[12px\]/);
  assert.match(s, /\btap\b/);
});

test('ListRow pressable rows carry tap', () => assert.match(src('ListRow'), /\btap\b/));
test('Badge is a pill', () => assert.match(src('Badge'), /rounded-full/));
test('Tabs fade the active tab in', () => assert.match(src('Tabs'), /fade-in/));
test('PageHeader title is 22 px, tight', () => {
  assert.match(src('PageHeader'), /text-\[22px\]/);
  assert.match(src('PageHeader'), /tracking-\[-0\.02em\]/);
});

test('no shadows or 16 px radii in ui/', () => {
  for (const f of readdirSync(new URL('.', import.meta.url)).filter((n) => n.endsWith('.jsx'))) {
    const s = readFileSync(new URL(`./${f}`, import.meta.url), 'utf8');
    assert.doesNotMatch(s, /shadow-/, f);
    assert.doesNotMatch(s, /rounded-\[16px\]/, f);
  }
});
