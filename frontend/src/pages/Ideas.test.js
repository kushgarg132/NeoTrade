import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Ideas.jsx');
const list = read('../components/ideas/PickList.jsx');
const pickBar = read('../components/ideas/PickBar.jsx');
const detail = read('./IdeaDetail.jsx');
const hold = read('../components/ideas/HoldingActions.jsx');

test('every row shows side, the expected move, how sure, the entry and one status; levels live on the idea page', () => {
  assert.match(list, /idea\.side/);
  assert.match(list, /`entry \$\{px\(idea\.entry\)\}`/);
  assert.match(list, /% up/);
  assert.match(list, /pickStatus\(idea, \{ news: news\?\.\[key\], results: results\?\.\[key\] \}\)/);
  assert.match(detail, /label="Stop"/);
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

test('rows only link to the idea page; Skip / Buy live there, keeping the real-money second tap', () => {
  assert.match(list, /to=\{`\/ideas\/\$\{encodeURIComponent\(idea\.id\)\}`\}/);
  assert.doesNotMatch(list, /<BuyBar|<PickBar|<Button/);
  assert.match(detail, /idea\.kind === 's' && !idea\.decided && <BuyBar idea=\{idea\} id=\{key\} onDone=\{done\} \/>/);
  assert.match(detail, /idea\.kind === 'p' && <PickBar idea=\{idea\} onDone=\{done\} \/>/);
  assert.match(bar, /Tap again to send\./);
  assert.match(bar, /confirm_token: token\.current/);
});

test('PickBar: Skip dismisses, Buy opens the order ticket at the pick levels', () => {
  assert.match(pickBar, /api\.post\(endpoints\.picks\.dismiss\(parseIdeaId\(idea\.id\)\.key\)\)/);
  assert.match(pickBar, /<OrderTicket symbol=\{idea\.symbol\} side="BUY" lastPrice=\{idea\.entry\} limitPrice=\{idea\.entryZone\?\.\[1\]\}/);
  assert.match(pickBar, /disabled=\{busy\}>Buy<\/Button>/);
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
  assert.match(page, /<Hero\b[\s\S]*label="Waiting for you"/);
  assert.match(page, /tab === 'holdings' && \(acts\.loading/);
});

test('one ranked list best first: engine ideas, then A and B together, C folded behind a toggle', () => {
  assert.match(page, /<PickList items=\{fresh\.data\.items\}/);
  assert.match(list, /rankPicks\(items\)/);
  assert.match(list, /Engine ideas/);
  assert.match(list, /Picks · best first/);
  assert.match(list, /hold to the due date/);
  assert.match(list, /aria-expanded=\{showUnproven\}/);
  assert.match(list, /C: no edge yet/);
  assert.match(list, /No proven setup has fired right now/);
  // column labels on wider screens only
  assert.match(list, /hidden sm:grid/);
});
