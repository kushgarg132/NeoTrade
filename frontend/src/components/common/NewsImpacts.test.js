import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source contract: every surface that shows a headline shows its analysis the News tab's way.
const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const surfaces = {
  chip: './NewsChip.jsx', holdingActions: '../ideas/HoldingActions.jsx',
  holdings: '../money/HoldingsTab.jsx', overview: '../money/OverviewTab.jsx', tax: '../money/TaxTab.jsx',
  journal: '../money/JournalTab.jsx', stockNews: '../stock/NewsTab.jsx', chart: '../stock/NewsStrip.jsx',
  today: '../home/TodayCard.jsx', sector: '../../pages/SectorPage.jsx', index: '../../pages/IndexPage.jsx',
};

test('every news surface renders ImpactChips', () => {
  for (const [name, p] of Object.entries(surfaces)) assert.match(rd(p), /<ImpactChips /, name);
});

test('a stored story opens its analysis page before the article', () => {
  const src = rd('./NewsImpacts.jsx');
  assert.match(src, /if \(id\) return <Link to=\{newsPath\(id\)\}/);
  assert.ok(src.indexOf('newsPath(id)') < src.indexOf('href={url}'));
});
