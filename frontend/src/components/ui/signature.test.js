import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = (f) => readFileSync(new URL(f, import.meta.url), 'utf8');
const hero = src('./Hero.jsx');
const chip = src('./DeltaChip.jsx');
const tile = src('./GradeTile.jsx');
const row = src('../home/HeroRow.jsx');

test('Hero: glow surface, 28px radius, private hero number, count-up honours reduced motion', () => {
  assert.match(hero, /var\(--glow\)/);
  assert.match(hero, /rounded-\[28px\]/);
  assert.match(hero, /hero-num/);
  assert.match(hero, /private/);
  assert.match(hero, /prefers-reduced-motion/);
  assert.match(hero, /requestAnimationFrame/);
  assert.match(hero, /cancelAnimationFrame/);
});

test('DeltaChip: up, down and neutral, private', () => {
  assert.match(chip, /▲/);
  assert.match(chip, /▼/);
  assert.match(chip, /--gain-soft/);
  assert.match(chip, /--loss-soft/);
  assert.match(chip, /--surface-2/);
  assert.match(chip, /private/);
});

test('Hero: private only when privateValue (default true)', () => {
  assert.match(hero, /privateValue = true/);
  assert.match(hero, /\$\{privateValue \? 'private ' : ''\}/);
});

test('DeltaChip: pluggable format, direction from pct when value is not a number', () => {
  assert.match(chip, /format = inr/);
  assert.match(chip, /privateValue = true/);
  assert.match(chip, /format\(value, \{ sign: true \}\)/);
  assert.match(chip, /typeof value !== 'number'/);
  assert.match(chip, /\$\{privateValue \? 'private ' : ''\}/);
});

test('GradeTile: A accent, B surface-2, C border, labelled', () => {
  assert.match(tile, /--accent-ink/);
  assert.match(tile, /--surface-2/);
  assert.match(tile, /--border/);
  assert.match(tile, /aria-label=\{`Grade \$\{grade\}`\}/);
});

test('HeroRow uses Hero and DeltaChip and keeps the NIFTY gap and meta lines', () => {
  assert.match(row, /import Hero /);
  assert.match(row, /import DeltaChip /);
  assert.match(row, /NIFTY/);
  assert.match(row, /sgnPts/);
  assert.match(row, /meta\.text/);
});
