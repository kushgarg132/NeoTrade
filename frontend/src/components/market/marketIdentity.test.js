import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const files = {
  sectors: src('./Sectors.jsx'),
  news: src('./News.jsx'),
  chips: src('../ui/ChipRow.jsx'),
  chart: src('../stock/TradingChart.jsx'),
  ticket: src('../trading/OrderTicket.jsx'),
  bar: src('../trading/TradingControlBar.jsx'),
};

test('no shadow, wash tokens, or accent fill with surface text', () => {
  for (const [name, s] of Object.entries(files)) {
    assert.doesNotMatch(s, /shadow-sm/, name);
    assert.doesNotMatch(s, /-wash\)/, name);
    assert.doesNotMatch(s, /bg-\[var\(--accent\)\] text-\[var\(--surface\)\]/, name);
  }
});

test('accent fills use accent-ink; ticket keeps text fill with surface text', () => {
  assert.match(files.chart, /text-\[var\(--accent-ink\)\]/);
  assert.match(files.chips, /text-\[var\(--accent-ink\)\]/);
  assert.match(files.ticket, /bg-\[var\(--text\)\] text-\[var\(--surface\)\]/);
});
