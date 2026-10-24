import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract checks for the Market page (no DOM runner here).
const pulse = readFileSync(new URL('../components/market/Pulse.jsx', import.meta.url), 'utf8');
const watch = readFileSync(new URL('../components/market/Watchlist.jsx', import.meta.url), 'utf8');

test('sector heatmap uses chartTheme heatColor and prints the signed %', () => {
  assert.match(pulse, /import \{[^}]*heatColor[^}]*\} from '..\/ui\/chartTheme'/);
  assert.match(pulse, /heatColor\(s\.change_pct/);
});

test('breadth is a Nifty 200 bar with a plain-words gloss', () => {
  assert.match(pulse, /Breadth/);
  assert.match(pulse, /advancing|rising/i);
});

test('gainers and losers are both visible without a tap', () => {
  assert.doesNotMatch(pulse, /data\[side\]/);
  assert.match(pulse, /data\.gainers/);
  assert.match(pulse, /data\.losers/);
});

test('52-week highs/lows explain themselves', () => {
  assert.match(pulse, /highest price in the past year/i);
});

test('the index card no longer shows a 4-index "breadth"', () => {
  assert.doesNotMatch(pulse, /breadth\(data/);
});

test('every empty section names an action', () => {
  for (const src of [pulse, watch]) {
    const empties = src.match(/<Empty\b[\s\S]*?\/>/g) || [];
    assert.ok(empties.length > 0);
    for (const e of empties) assert.match(e, /action=/);
  }
});

test('market quotes are not blurred by hide-amounts', () => {
  // ListRow blurs its value unless privateValue={false}: every Pulse row must opt out.
  assert.equal((pulse.match(/<ListRow /g) || []).length, (pulse.match(/<ListRow privateValue=\{false\} /g) || []).length);
});

test('dark heat steps keep the % figure readable (step 3 mixes at most 50%)', () => {
  const css = readFileSync(new URL('../index.css', import.meta.url), 'utf8');
  const dark = css.slice(css.indexOf('  .dark {'));
  assert.match(dark, /--heat-pos-3: color-mix\(in oklab, var\(--gain\) 50%/);
  assert.match(dark, /--heat-neg-3: color-mix\(in oklab, var\(--loss\) 50%/);
  assert.doesNotMatch(pulse, /opacity-80/);
});
