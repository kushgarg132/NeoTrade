import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const f = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const layout = f('../Layout.jsx');
const chat = f('../ChatWidget.jsx');
const chip = f('./NewsChip.jsx');
const files = [layout, chat, chip, f('./StopAutopilot.jsx')];

test('shared chrome: no doc-meta, shadow- or sheet classes', () => {
  for (const s of files) {
    assert.doesNotMatch(s, /doc-meta/);
    assert.doesNotMatch(s, /shadow-/);
    assert.doesNotMatch(s, /["' ]sheet[ "']/);
  }
});

test('layout toast is a plain bordered card', () => {
  assert.match(layout, /rounded-\[12px\]/);
  assert.match(layout, /border-\[var\(--border\)\]/);
});

test('chat launcher keeps its border; truncation survives', () => {
  assert.match(chat, /border border-\[var\(--border\)\]/);
  assert.match(chat, /truncate/);
  assert.match(chip, /truncate/);
});
