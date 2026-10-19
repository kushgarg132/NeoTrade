import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseBlocks, parseInline, plainText } from './aiMarkdown.js';
import { oneLine } from './aiText.js';

test('blocks: headings, paragraphs, bullets, numbers, rules', () => {
  const b = parseBlocks('## Snapshot\n\n### What moved\nNifty fell.\nBanks led.\n\n- **Concentration**: 25%\n- second\n\n1. one\n2. two\n\n---\nEnd');
  assert.deepEqual(b.map((x) => x.type), ['heading', 'heading', 'p', 'ul', 'ol', 'hr', 'p']);
  assert.equal(b[0].text, 'Snapshot');
  assert.equal(b[2].text, 'Nifty fell. Banks led.');
  assert.deepEqual(b[3].items, ['**Concentration**: 25%', 'second']);
  assert.deepEqual(b[4].items, ['one', 'two']);
});

test('inline: bold, italic, rupee amounts, no HTML', () => {
  const p = parseInline('**FIIs** sold ₹1,149 cr; *calm* <b>x</b>');
  assert.deepEqual(p.filter((s) => s.bold).map((s) => s.text), ['FIIs']);
  assert.deepEqual(p.filter((s) => s.italic).map((s) => s.text), ['calm']);
  assert.deepEqual(p.filter((s) => s.amount).map((s) => s.text), ['₹1,149 cr']);
  assert.ok(p.some((s) => s.text.includes('<b>x</b>')), 'HTML stays literal text');
});

test('plainText strips markdown; oneLine skips headings and meta lines', () => {
  assert.equal(plainText('### A **bold** *move*'), 'A bold move');
  const note = '# GOLDBEES — Research Note\n*Nippon India ETF | Mon 19 Oct*\n\n---\n\n### Market Sentiment\n**Neutral** — No company news. More text.';
  assert.equal(oneLine(note), 'Neutral — No company news.');
});

test('summaryLines drops markdown heading/list marks and rules', async () => {
  const { summaryLines } = await import('./summaries.js');
  assert.deepEqual(summaryLines('### Your day\n- **Up** ₹1,840\n---\n1. Market fell'), ['Your day', '**Up** ₹1,840', 'Market fell']);
});

test('underscores inside words stay literal', () => {
  const p = parseInline('earnings_falling_3q and _calm_ day');
  assert.deepEqual(p.filter((s) => s.italic).map((s) => s.text), ['calm']);
  assert.ok(p.map((s) => s.text).join('').includes('earnings_falling_3q'));
});

test('collapseBlocks keeps 5 paragraphs/items, cuts a long list part-way', async () => {
  const { collapseBlocks, contentUnits } = await import('./aiMarkdown.js');
  const b = parseBlocks('### A\nOne.\n\n### B\n- 1\n- 2\n- 3\n- 4\n- 5\n- 6\n\n### C\nLast.');
  assert.equal(contentUnits(b), 8);
  const c = collapseBlocks(b);
  assert.deepEqual(c.map((x) => x.type), ['heading', 'p', 'heading', 'ul']);
  assert.equal(c[3].items.length, 4);
});
