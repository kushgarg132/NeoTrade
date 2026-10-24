import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SERIES, heatColor, AXIS, GRID, TOOLTIP_STYLE } from './chartTheme.js';

test('heatColor buckets a % change onto the diverging ramp', () => {
  assert.equal(heatColor(0), 'var(--heat-0)');
  assert.equal(heatColor(5), 'var(--heat-pos-3)');
  assert.equal(heatColor(-0.5), 'var(--heat-neg-1)');
  assert.equal(heatColor(-9), 'var(--heat-neg-3)');
  assert.equal(heatColor(NaN), 'var(--heat-0)');
  assert.equal(heatColor(null), 'var(--heat-0)');
});

test('six categorical series, fixed order', () => {
  assert.equal(SERIES.length, 6);
  assert.equal(SERIES[0], 'var(--chart-1)');
});

test('every var the theme names is defined in index.css, light and dark', () => {
  const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
  const used = JSON.stringify([SERIES, AXIS, GRID, TOOLTIP_STYLE])
    + [-9, -2, -0.5, 0, 0.5, 2, 9].map(heatColor).join();
  const names = new Set(used.match(/--[a-z0-9-]+/g));
  const dark = css.split('.dark {')[1];
  for (const n of names) {
    assert.match(css, new RegExp(`${n}:`), `${n} missing in :root`);
    if (n.startsWith('--chart') || n.startsWith('--heat')) assert.match(dark, new RegExp(`${n}:`), `${n} missing in .dark`);
  }
});
