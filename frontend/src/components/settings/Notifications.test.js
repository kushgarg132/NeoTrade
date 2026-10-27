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
  assert.match(notif, /endpoints\.settings\.preferences, \{ news_alerts/);
  for (const l of ['Held', 'Held + watched', 'All', 'Off']) assert.ok(notif.includes(`'${l}'`));
});
