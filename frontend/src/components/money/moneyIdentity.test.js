import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const css = rd('../../index.css');
const holdings = rd('./HoldingsTab.jsx');
const rebalance = rd('../portfolio/Rebalance.jsx');
const files = Object.fromEntries(
  readdirSync(new URL('.', import.meta.url)).filter((f) => f.endsWith('.jsx')).map((f) => [f, rd(`./${f}`)])
);
files['Rebalance.jsx'] = rebalance;

test('sheet utility radius is 20px', () => {
  const i = css.indexOf('@utility sheet');
  assert.match(css.slice(i, css.indexOf('}', i)), /border-radius: 20px/);
});

test('doc-meta comment no longer says typewriter', () => {
  const i = css.indexOf('@utility doc-meta');
  assert.doesNotMatch(css.slice(css.lastIndexOf('/*', i), i), /typewriter/i);
});

test('no legacy classes in money files', () => {
  for (const [n, s] of Object.entries(files)) {
    for (const bad of ['rounded-[16px]', 'rounded-t-[16px]', 'border-dashed', '-wash)', 'bg-[var(--accent)] text-[var(--surface)]']) {
      assert.ok(!s.includes(bad), `${n} contains ${bad}`);
    }
  }
});

test('accent-ink on Chip on-state; rule toggle untouched', () => {
  assert.match(holdings, /on \? `\$\{onCls\} text-\[var\(--accent-ink\)\]/);
  assert.ok(rebalance.includes('bg-[var(--text)] text-[var(--surface)]'));
});
