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

test('inline: signed percents and amounts take a tone; known tickers become symbols', async () => {
  const { parseInline: p } = await import('./aiMarkdown.js');
  const segs = p('INFY rose +2.4% while TCS fell −1.1% and NIFTY lost -₹500; RSI 60%', new Set(['INFY', 'TCS']));
  assert.deepEqual(segs.filter((s) => s.symbol).map((s) => s.symbol), ['INFY', 'TCS']);
  assert.deepEqual(segs.filter((s) => s.pct).map((s) => [s.text, s.tone]), [['+2.4%', 'gain'], ['−1.1%', 'loss']]);
  assert.deepEqual(segs.filter((s) => s.amount).map((s) => [s.text, s.tone]), [['-₹500', 'loss']]);
  assert.equal(segs.map((s) => s.text).join(''), 'INFY rose +2.4% while TCS fell −1.1% and NIFTY lost -₹500; RSI 60%');
  assert.ok(!p('INFY up', undefined).some((s) => s.symbol), 'no symbols without a known set');
});

test('tickerCandidates skips market words and keeps order', async () => {
  const { tickerCandidates } = await import('./aiMarkdown.js');
  assert.deepEqual(tickerCandidates('NIFTY fell; HDFCBANK and M&M led, RSI high, HDFCBANK again, FIIs sold'), ['HDFCBANK']);
  assert.deepEqual(tickerCandidates('BAJAJ-AUTO and TATAMOTORS'), ['BAJAJ-AUTO', 'TATAMOTORS']);
});

test('outline: key points first, headings become sections', async () => {
  const { outline } = await import('./aiMarkdown.js');
  const o = outline(parseBlocks('- a\n- b\n- c\n- d\n\nMore.\n\n## Risks\nOne.\n\n## Empty\n\n## Next\n- x'));
  assert.deepEqual(o.lead.items, ['a', 'b', 'c']);
  assert.deepEqual(o.intro.map((b) => b.type), ['ul', 'p']);
  assert.deepEqual(o.sections.map((s) => s.title), ['Risks', 'Next']);
  const h = outline(parseBlocks('## Snapshot\nNifty fell.\nMore.\n\n## Why\nRates.'));
  assert.equal(h.leadTitle, 'Snapshot');
  assert.equal(h.lead.text, 'Nifty fell. More.');
  assert.deepEqual(h.sections.map((s) => s.title), ['Why']);
  assert.equal(outline([]).lead, null);
});

test('followUps: tickers first, then an action or meaning question', async () => {
  const { followUps } = await import('./aiMarkdown.js');
  assert.deepEqual(followUps('Trim INFY.', ['INFY', 'TCS', 'SBIN']), ['Why INFY?', 'Why TCS?', 'What should I do now?']);
  assert.deepEqual(followUps('Markets were calm.', []), ['What does this mean for me?', 'Explain this simply']);
});
