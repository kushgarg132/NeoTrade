import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Ideas.jsx');
const list = read('../components/ideas/PickList.jsx');
const pickBar = read('../components/ideas/PickBar.jsx');
const detail = read('./IdeaDetail.jsx');
const hold = read('../components/ideas/HoldingActions.jsx');
const bar = read('../components/ideas/BuyBar.jsx');
const ideas = read('../utils/ideas.js');

test('one page, two lanes: holdings first, then new picks; no sub-tabs', () => {
  assert.doesNotMatch(page, /<Tabs\b/);
  assert.ok(page.indexOf('title="Decide on your holdings"') < page.indexOf('title="New picks"'));
  assert.match(page, /<Lane id="holdings"/);
  assert.match(page, /<Lane id="picks"/);
});

test('the Hero is the picks forward record, labelled paper and not advice', () => {
  assert.match(page, /<Hero\b[\s\S]*label="Picks that beat NIFTY"/);
  assert.match(page, /rec\.beat_nifty_rate/);
  assert.match(page, /of \{FORWARD_NEEDED\}/);
  assert.match(page, /Paper record · not advice/);
  assert.match(page, /kind="paper"/);
});

test('both lanes keep loading, error and empty states, and the admin gate is kept', () => {
  assert.match(page, /Could not load your holdings alerts\./);
  assert.match(page, /Could not load ideas\./);
  assert.match(page, /<Empty[^>]*action=/);
  assert.match(hold, /You're clear\./);
  assert.match(page, /role === 'admin'/);
});

test('a pick row: two lines of facts and one status, linking only to the idea page', () => {
  assert.match(list, /idea\.side/);
  assert.match(list, /% up/);
  assert.match(list, /pickStatus\(idea, \{ news: news\?\.\[key\], results: results\?\.\[key\] \}\)/);
  assert.match(list, /to=\{`\/ideas\/\$\{encodeURIComponent\(idea\.id\)\}`\}/);
  assert.doesNotMatch(list, /<BuyBar|<PickBar|<Button/);
});

test('picks best first, C folded behind a toggle, the hold rule stated once', () => {
  assert.match(list, /rankPicks\(items\)/);
  assert.match(list, /aria-expanded=\{showUnproven\}/);
  assert.match(list, /C: no edge yet/);
  assert.match(list, /No proven setup has fired right now/);
  assert.match(list, /hold to the due date/);
});

test('a pick already under its stop says so before anything else', () => {
  assert.match(ideas, /idea\.priceNow < idea\.stop\) return \{ label: 'Below stop', kind: 'alert' \}/);
  assert.match(ideas, /priceNow: typeof p\.price_now === 'number'/);
});

test('holdings lane: one row per stock with the stamp; a tap opens signals, Later and the row\'s own dismiss', () => {
  assert.match(hold, /triageHoldings\(actions\)/);
  assert.match(hold, /<Stamp side=\{b\.primary\.label\}/);
  assert.match(hold, /aria-expanded=\{open\}/);
  assert.match(hold, /const b = holdingButtons\(lead\)/);
  assert.match(hold, /\{b\.dismiss\}/);
  assert.match(hold, /`\$\{b\.later\}: hide for 7 days`/);
  assert.match(hold, /<ReadLink action=\{a\.action\} \/>/);
  assert.match(hold, /for your information/);
});

test('Skip / Buy live on the idea page, keeping the real-money second tap', () => {
  assert.match(detail, /idea\.kind === 's' && !idea\.decided && <BuyBar idea=\{idea\} id=\{key\} onDone=\{done\} \/>/);
  assert.match(detail, /idea\.kind === 'p' && <PickBar idea=\{idea\} onDone=\{done\} broken=/);
  assert.match(bar, /Tap again to send\./);
  assert.match(bar, /confirm_token: token\.current/);
});

test('PickBar: Skip dismisses, Buy opens the order ticket at the pick levels', () => {
  assert.match(pickBar, /api\.post\(endpoints\.picks\.dismiss\(parseIdeaId\(idea\.id\)\.key\)\)/);
  assert.match(pickBar, /<OrderTicket symbol=\{idea\.symbol\} side="BUY" lastPrice=\{idea\.priceNow \?\? idea\.entry\} limitPrice=\{broken \? undefined : idea\.entryZone\?\.\[1\]\}/);
  assert.match(pickBar, /disabled=\{busy\}>Buy<\/Button>/);
  assert.match(pickBar, /variant=\{broken \? 'secondary' : 'primary'\}/); // quieter once the stop broke
});
