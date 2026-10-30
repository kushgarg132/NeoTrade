import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  settingsRedirect, accountsOf, needsYou, guardrailsLine, portfolioLine, goalLine, autopilotLine, modelLine, alertsLine, NEWS_ALERTS,
} from './settings.js';

// A sentence as plain text, chips in brackets: easy to assert on.
const text = (parts) => parts.map((p) => (typeof p === 'string' ? p : `[${p.v}]`)).join('');

test('settingsRedirect maps every tab, keeps other params', () => {
  const want = {
    accounts: '/settings/brokers', broker: '/settings/brokers', limits: '/settings/guardrails', portfolio: '/settings/portfolio',
    safety: '/settings/guardrails', guardrails: '/settings/guardrails', alerts: '/settings/notifications', profile: '/profile',
    ai: '/settings/ai', goal: '/settings/goal', theme: '/settings', lab: '/settings/lab', about: '/settings/lab', beta: '/settings/lab',
    nope: '/settings',
  };
  for (const [tab, to] of Object.entries(want)) assert.equal(settingsRedirect(`?tab=${tab}`), to, tab);
  assert.equal(settingsRedirect('?tab=accounts&code=abc'), '/settings/brokers?code=abc');
  assert.equal(settingsRedirect(''), null);
  assert.equal(settingsRedirect('?code=x'), null);
});

test('lines are null until their data loads', () => {
  for (const f of [guardrailsLine, portfolioLine, goalLine, autopilotLine, modelLine]) assert.equal(f(undefined), null);
  assert.equal(alertsLine(undefined, {}), null);
  assert.equal(alertsLine({ linked: true }, undefined), null);
});

test('guardrailsLine: off, no daily limit, trades optional', () => {
  assert.equal(text(guardrailsLine({ guardrails_enabled: false, daily_loss_limit: 5000 })), 'Guardrails are [off].');
  assert.equal(text(guardrailsLine({ guardrails_enabled: true, daily_loss_limit: 5000, max_trades_per_day: 6 })),
    'Guardrails stop you at [₹5,000] lost a day and [6] trades.');
  assert.equal(text(guardrailsLine({ guardrails_enabled: true, daily_loss_limit: 0, max_trades_per_day: 0 })), 'Guardrails have [no daily limit].');
});

test('portfolio, goal, autopilot, model, alerts', () => {
  assert.equal(text(portfolioLine({ portfolio_max_loss_pct: 25, portfolio_max_weight_pct: 20 })),
    'Review flags a holding [25%] under cost or over [20%] of the whole.');
  assert.equal(text(goalLine({ goal: null })), 'No goal [set one].');
  assert.equal(text(goalLine({ goal: { kind: 'beat_nifty', target: 2, by: '2027-03-31' } })), 'Goal: beat [NIFTY] by [Mar 2027].');
  const value = goalLine({ goal: { kind: 'value', target: 2500000, by: '2027-12-31' } });
  assert.equal(text(value), 'Goal: [₹25,00,000] by [Dec 2027].');
  assert.equal(value[1].private, true);
  assert.equal(text(autopilotLine({})), 'Autopilot is [off].');
  assert.equal(text(autopilotLine({ autopilot_enabled: true })), 'Autopilot trades on [paper], news entries [off].');
  const live = autopilotLine({ autopilot_enabled: true, autopilot_live: true, autopilot_news: true });
  assert.equal(text(live), 'Autopilot trades on [live money], news entries [on].');
  assert.equal(live[1].tone, 'loss');
  assert.equal(text(modelLine({ tiers: { deep: 'agy/claude-opus-4-6' }, fallback: 'cx/gpt' })), 'AI answers with [claude-opus-4-6].');
  assert.equal(text(modelLine({ tiers: {}, fallback: 'cx/gpt-5.6-luna' })), 'AI answers with [gpt-5.6-luna].');
  assert.equal(modelLine({ tiers: {} }), null);
  assert.equal(text(alertsLine({ linked: true }, {})), 'Telegram [linked]; news alerts for [held stocks].');
  assert.equal(text(alertsLine({ linked: false }, { news_alerts: 'off' })), 'Telegram [not linked]; news alerts [off].');
});

test('accountsOf: /today when loaded, else roles without a state', () => {
  const today = { accounts: { mine: { broker: 'kite', state: 'ACTIVE' } } };
  assert.equal(accountsOf({ broker_roles: { upstox: 'ai' } }, today), today.accounts);
  assert.deepEqual(accountsOf({ broker_roles: { upstox: 'ai' } }, null), { ai: { broker: 'upstox', state: null } });
  assert.deepEqual(accountsOf(undefined, null), {});
});

test('needsYou: broken sessions, kill switch, Telegram; nothing when all is well', () => {
  const accounts = {
    mine: { broker: 'kite', state: 'ACTIVE' }, ai: { broker: 'upstox', state: 'DEGRADED' },
  };
  const items = needsYou({ accounts, today: { kill_switch: { tripped: true } }, telegram: { linked: false } });
  assert.deepEqual(items.map((i) => i.text), [
    'Upstox (AI account) session expired', 'Daily loss limit hit: live trading stopped', 'Telegram not linked: alerts reach only this app',
  ]);
  assert.equal(items[0].to, '/settings/brokers?broker=upstox');
  assert.equal(needsYou({ accounts: { mine: { broker: 'kite', state: 'NEEDS_LOGIN' } } })[0].action, 'Log in');
  assert.equal(needsYou({ accounts: { ai: { broker: 'angel_one', state: 'UNCONFIGURED' } } })[0].text, 'Angel One (AI account) has no API keys');
  assert.equal(needsYou({ accounts: {} })[0].text, 'No broker connected');
  // Unknown state (/today failed) and unknown Telegram say nothing.
  assert.deepEqual(needsYou({ accounts: { mine: { broker: 'kite', state: null } }, telegram: undefined }), []);
  assert.deepEqual(needsYou({ accounts: { mine: { broker: 'kite', state: 'ACTIVE' } }, today: {}, telegram: { linked: true } }), []);
});

test('NEWS_ALERTS', () => {
  assert.deepEqual(NEWS_ALERTS.map(([k]) => k), ['held', 'held+watched', 'all', 'off']);
});
