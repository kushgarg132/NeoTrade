import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./IdeaDetail.jsx', import.meta.url), 'utf8');
const levels = readFileSync(new URL('../components/ideas/LevelsLine.jsx', import.meta.url), 'utf8');
const at = (re) => src.search(re);

test('lead, then the trade plan on one price line, then why, the range and the track record', () => {
  const lead = at(/<Lead idea=\{idea\} \/>/), plan = at(/<LevelsLine /), why = at(/<Card title="Why this idea">/);
  assert.ok(lead > 0 && plan > lead && why > plan && at(/<Fold title="Track record/) > why);
  assert.match(src, /label="Reward : risk"/);
  assert.match(src, /label="To stop"/);
  assert.match(levels, /Stop/);
  assert.match(levels, /Target/);
  assert.match(levels, /Now \{px\(now\)\}/);
});

test('Skip / Buy sit in a fixed bar like the Stock page', () => {
  assert.match(src, /fixed z-30 inset-x-0 bottom-\[calc\(3\.5rem\+env\(safe-area-inset-bottom\)\)\] lg:bottom-0 lg:left-56/);
});

test('figures carry a paper line and the jargon is glossed', () => {
  assert.match(src, /Paper record · not advice/);
  assert.match(src, /kind="paper"/);
  assert.match(src, /p10/);
  assert.match(src, /held back/i);
  assert.match(src, /t-score/);
});

test('confidence is one line; the second-tap BuyBar and gates are untouched', () => {
  assert.match(src, /Confidence <b>/);
  assert.match(src, /<BuyBar idea=\{idea\} id=\{key\} onDone=\{done\}/);
  assert.match(src, /Empty title="Idea not found"/);
});

test('the lead names the grade in words beside its tile and shows the expected move once', () => {
  assert.match(src, /GRADES\[idea\.grade\] && \(/);
  assert.match(src, /<GradeTile grade=\{idea\.grade\} small \/>\{GRADE_NAME\[idea\.grade\]\}/);
  assert.doesNotMatch(src, /<Badge kind=\{GRADES\[/);
  assert.match(src, /idea\.rupees/);
  assert.match(src, /chance up/);
});

test('Fold uses the 20px radius', () => {
  const fold = src.slice(at(/const Fold =/), at(/const StrategyRecord/));
  assert.match(fold, /rounded-\[20px\]/);
});
