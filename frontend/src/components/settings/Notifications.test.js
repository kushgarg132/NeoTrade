import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const sheet = rd('../journal/GuardrailsSheet.jsx');
const tg = rd('./TelegramLink.jsx');
const notif = rd('./Notifications.jsx');

test('Telegram link/verify/bot endpoints moved out of the guardrails sheet', () => {
  for (const k of ['guardrails.link', 'guardrails.verify', 'guardrails.telegramBot']) {
    assert.ok(!sheet.includes(k), `sheet still has ${k}`);
    assert.ok(tg.includes(k), `TelegramLink lacks ${k}`);
  }
});

test('Notifications renders TelegramLink and writes news_alerts', () => {
  assert.match(notif, /<TelegramLink \/>/);
  assert.match(notif, /news_alerts: id \}/);
  assert.match(notif, /import \{ NEWS_ALERTS \} from '\.\.\/\.\.\/utils\/settings'/);
});

test('Notifications has a toggle per alert kind (on = not muted) and the impact threshold', () => {
  for (const k of ['exit', 'money', 'news_breaking', 'action', 'ideas', 'stale_ideas', 'news', 'learning', 'review', 'autopilot_refused']) {
    assert.match(notif, new RegExp(`\\['${k}', '`), `no row for ${k}`);
  }
  assert.match(notif, /on=\{!mute\[kind\]\}/);
  assert.match(notif, /label=\{label\}/);
  assert.match(notif, /\{ alert_mute: next \}/);
  assert.match(notif, /\{ breaking_news_min: n \}/);
  assert.match(notif, /Breaking news from impact/);
  assert.match(notif, /`\$\{n\}\/10`/);
});

test('a failed PUT reverts the toggle and the threshold', () => {
  assert.match(notif, /setMute\(\(m\) => undoMute\(m, kind, was\)\)/);
  assert.match(notif, /setMinImpact\(prev\)/);
  assert.match(notif, /\.catch\(\(err\) => \{\s*revert\(\);/);
});

test('the save-error note renders in the sheet whose control failed', () => {
  assert.match(notif, /setNote\(\{ at, text:/);
  for (const at of ['news', 'instant', 'digest', 'impact']) {
    assert.match(notif, new RegExp(`noteAt\\('${at}'\\)`), `no note slot for ${at}`);
  }
  assert.match(notif, /flip\(kind, at\)/);
});

test('controls wait for the GET and for an in-flight save', () => {
  assert.match(notif, /setLoaded\(true\)/);
  assert.match(notif, /setLoaded\(false\)/);
  assert.match(notif, /loaded === null \? <Ruling/);
  assert.match(notif, /disabled=\{busy\}/);
  assert.match(notif, /\.finally\(\(\) => setBusy\(false\)\)/);
  assert.match(notif, /detailToText\(/);
});
