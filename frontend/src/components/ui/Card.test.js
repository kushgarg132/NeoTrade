import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the contract in the source.
const src = readFileSync(new URL('./Card.jsx', import.meta.url), 'utf8');

test('a card with `to` is one Link with a chevron', () => {
  assert.match(src, /to \?/);
  assert.match(src, /<Link to=\{to\}/);
  assert.match(src, /<ChevronRight/);
});

test('`more` renders its label in a Link to more.to', () => {
  assert.match(src, /<Link to=\{more\.to\}/);
  assert.match(src, /more\.label/);
});

test('docstring says to and more are never both', () => {
  assert.match(src, /never both/);
});

// A guard, not a red test: it passed before the Task 8 sweep and must keep passing.
test('no <Card> gets both `to` and `more`', async () => {
  const { readdirSync, statSync } = await import('node:fs');
  const files = [];
  const walk = (d) => readdirSync(d).forEach((n) => {
    const p = `${d}/${n}`;
    if (statSync(p).isDirectory()) walk(p); else if (p.endsWith('.jsx')) files.push(p);
  });
  walk(new URL('../../', import.meta.url).pathname);
  for (const f of files) {
    for (const [tag] of readFileSync(f, 'utf8').matchAll(/<Card\b[^>]*?>/gs)) {
      assert.ok(!(/\sto=/.test(tag) && /\smore=/.test(tag)), `${f}: ${tag.slice(0, 80)}`);
    }
  }
});
