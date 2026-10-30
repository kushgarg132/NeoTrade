import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('./index.css', import.meta.url), 'utf8');
const ctx = readFileSync(new URL('./context/ThemeContext.jsx', import.meta.url), 'utf8');

const block = (start) => {
  const i = css.indexOf(start);
  return css.slice(i, css.indexOf('\n  }\n', i));
};
const tokens = (b) =>
  Object.fromEntries([...b.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2].toLowerCase()]));
const themes = { light: tokens(block(':root {')), dark: tokens(block('.dark {')) };

const lum = (hex) => {
  const c = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

for (const [name, t] of Object.entries(themes)) {
  test(`${name}: text contrast`, () => {
    for (const fg of ['text', 'text-muted'])
      for (const bg of ['bg', 'surface', 'surface-2'])
        assert.ok(ratio(t[fg], t[bg]) >= 4.5, `${fg} on ${bg}: ${ratio(t[fg], t[bg]).toFixed(2)}`);
  });
  test(`${name}: gain/loss on surface, ink on accent`, () => {
    for (const fg of ['gain', 'loss'])
      assert.ok(ratio(t[fg], t.surface) >= 4.5, `${fg}: ${ratio(t[fg], t.surface).toFixed(2)}`);
    assert.ok(ratio(t['accent-ink'], t.accent) >= 4.5, `accent-ink: ${ratio(t['accent-ink'], t.accent).toFixed(2)}`);
  });
}

test('dark hero values', () => {
  const d = themes.dark;
  assert.equal(d.bg, '#0b0b0c');
  assert.equal(d.accent, '#10b981');
  assert.equal(d.gain, '#3ddc97');
  assert.equal(d.loss, '#ff6b6b');
});

test('neutrals are gray: no green cast in bg, surfaces, border or text', () => {
  for (const t of Object.values(themes))
    for (const k of ['bg', 'surface', 'surface-2', 'border', 'text', 'text-muted']) {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(t[k].slice(i, i + 2), 16));
      assert.ok(g - Math.min(r, b) <= 3, `${k} ${t[k]} leans green`);
    }
});

test('font, theme default, motion', () => {
  assert.match(css, /--font-sans:\s*"Geist"/);
  assert.ok(!ctx.includes('prefers-color-scheme'));
  assert.match(ctx, /return 'dark'/);
  assert.match(css, /\.tap\s*\{/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
