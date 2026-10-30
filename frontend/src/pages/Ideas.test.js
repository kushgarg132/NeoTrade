import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Ideas.jsx');
const row = read('../components/ideas/IdeaRow.jsx');
const hold = read('../components/ideas/HoldingActions.jsx');

test('every idea row shows side, entry, stop and R:R without a tap', () => {
  assert.match(row, /idea\.side/);
  assert.match(row, /Entry/);
  assert.match(row, /SL /);
  assert.match(row, /R:R/);
});

test('the list says its figures are a paper record, not advice', () => {
  assert.match(page, /Paper record · not advice/);
  assert.match(page, /kind="paper"/);
});

test('both sections have an Empty that names an action, and the admin gate is kept', () => {
  assert.match(hold, /<Empty[^>]*action=/);
  assert.match(page, /<Empty[^>]*action=/);
  assert.match(page, /role === 'admin'/);
});

test('the holdings alert error names what is affected', () => {
  assert.match(page, /Could not load your holdings alerts\./);
});

const bar = read('../components/ideas/BuyBar.jsx');

test('a pending engine idea gets its own Skip / Buy N SYMBOL bar in the row, Picks do not', () => {
  assert.match(row, /idea\.kind === 's' && !idea\.decided && onDone/);
  assert.match(row, /<BuyBar idea=\{idea\} id=\{parseIdeaId\(idea\.id\)\.key\} onDone=\{onDone\} compact/);
  assert.match(bar, /compact \? verb :/);
  assert.match(page, /<IdeaRow key=\{i\.id\} idea=\{i\} onDone=\{fresh\.reload\}/);
});

test('the row buttons never open the detail page and keep the real-money second tap', () => {
  // The info part is the link; the bar sits outside it.
  assert.ok(row.indexOf('</Link>') < row.indexOf('<BuyBar'));
  assert.match(bar, /Tap again to send\./);
  assert.match(bar, /confirm_token: token\.current/);
});

test('a pick row gets Skip (dismiss) and Buy SYMBOL… that opens the order ticket at the pick levels', () => {
  assert.match(row, /idea\.kind === 'p' && onDone/);
  assert.match(row, /api\.post\(endpoints\.picks\.dismiss\(parseIdeaId\(idea\.id\)\.key\)\)/);
  assert.match(row, /<OrderTicket symbol=\{idea\.symbol\} side="BUY" lastPrice=\{idea\.entry\} limitPrice=\{idea\.entryZone\?\.\[1\]\}/);
  assert.match(row, /disabled=\{busy\}>Buy<\/Button>/);
});

test('holdings triage into Act now (one card per stock, its own labels), Keep an eye and Coming up', () => {
  assert.match(hold, /triageHoldings\(actions\)/);
  assert.match(hold, /title="Act now"/);
  assert.match(hold, /title="Keep an eye"/);
  assert.match(hold, /title="Coming up"/);
  assert.match(hold, /const b = holdingButtons\(lead\)/);
  assert.match(hold, /\{b\.primary\.label\}/);
  assert.match(hold, /\{b\.dismiss\}/);
  assert.match(hold, /`\$\{b\.later\}: hide for 7 days`/);
  assert.match(hold, /<ReadLink action=\{a\.action\} \/>/);
  assert.match(hold, /You're clear\./);
});

test('Ideas splits into Picks (default) and Holdings sub-tabs', () => {
  assert.match(page, /const IDS = \['picks', 'holdings'\]/);
  assert.match(page, /tab === 'picks' && <div className="space-y-3">/);
  assert.match(page, />New ideas<\/h2>/);
  assert.match(page, /tab === 'holdings' && \(acts\.loading/);
});

test('picks are grouped Engine, A, B, then C behind the toggle', () => {
  const group = page.slice(page.indexOf('const group ='), page.indexOf('return ('));
  assert.match(page, /groupByGrade/);
  assert.doesNotMatch(page, /splitByEvidence/);
  assert.match(page, /Engine ideas/);
  assert.match(page, /GRADES\.A\.label/);
  assert.match(page, /GRADES\.B\.label/);
  assert.match(page, /aria-expanded=\{showUnproven\}/);
  assert.match(page, /grade C: no edge yet/);
  // groups render only when non-empty; the toggle and the "No proven setup" line need picks
  assert.match(page, /rows\.length > 0 &&/);
  assert.match(page, /C\.length > 0 &&/);
  assert.match(page, /engine\.length === 0 && A\.length === 0 && B\.length === 0 && C\.length > 0/);
  // toggle state lives in Ideas, not in a group, so it survives fresh.reload
  assert.ok(page.indexOf('useState(false)') < page.indexOf('const group ='));
  assert.doesNotMatch(group, /useState/);
});
