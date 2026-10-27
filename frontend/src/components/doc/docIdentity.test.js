import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const doc = rd('./Doc.jsx');
const files = { Doc: doc, Strategies: rd('../../pages/Strategies.jsx') };

test('Strategies and Doc carry no legacy identity classes', () => {
  for (const [n, s] of Object.entries(files)) {
    for (const bad of ['rounded-[16px]', 'border-dashed', '-wash)', 'shadow-sm', 'bg-[var(--accent)] text-[var(--surface)]'])
      assert.ok(!s.includes(bad), `${n} still has ${bad}`);
  }
});

test('Doc count badge uses accent-ink and chips use soft tones', () => {
  assert.ok(doc.includes('text-[var(--accent-ink)]'));
  assert.ok(doc.includes('--gain-soft') && doc.includes('--loss-soft'));
});
