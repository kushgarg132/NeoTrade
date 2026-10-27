import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

test('the old tab strip is gone', () => {
  for (const f of ['../components/layout/sections.js', '../components/layout/SectionTabs.jsx', '../components/paper/PaperShell.jsx']) {
    assert.ok(!existsSync(new URL(f, import.meta.url)), f);
  }
});

test('Beta shows an ErrorLine with Retry instead of going blank', () => {
  const src = readFileSync(new URL('../components/settings/Beta.jsx', import.meta.url), 'utf8');
  assert.ok(src.includes('<ErrorLine') && src.includes('onRetry') && src.includes('<Skeleton'));
  assert.ok(!src.includes('return null'));
});
