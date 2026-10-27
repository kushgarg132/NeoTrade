import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  settingsRedirect, brokersState, guardrailsState, portfolioState, telegramState, goalState, modelState, autopilotState, NEWS_ALERTS,
} from './settings.js';

test('settingsRedirect maps every tab, keeps other params', () => {
  const want = {
    accounts: '/settings/brokers', broker: '/settings/brokers', limits: '/settings/guardrails', portfolio: '/settings/guardrails',
    safety: '/settings/guardrails', guardrails: '/settings/guardrails', alerts: '/settings/notifications', profile: '/settings/profile',
    ai: '/settings/ai', goal: '/settings/goal', theme: '/settings', lab: '/settings/lab', about: '/settings/lab', beta: '/settings/lab',
    nope: '/settings',
  };
  for (const [tab, to] of Object.entries(want)) assert.equal(settingsRedirect(`?tab=${tab}`), to, tab);
  assert.equal(settingsRedirect('?tab=accounts&code=abc'), '/settings/brokers?code=abc');
  assert.equal(settingsRedirect(''), null);
  assert.equal(settingsRedirect('?code=x'), null);
});

test('states fall back to a dash without prefs', () => {
  for (const f of [brokersState, guardrailsState, portfolioState, goalState, modelState, autopilotState]) assert.equal(f(undefined), '–');
  assert.equal(telegramState(null), '–');
});

test('brokersState', () => {
  assert.equal(brokersState({ broker_roles: { kite: 'mine', upstox: 'ai' } }), 'Kite: yours · Upstox: AI');
  assert.equal(brokersState({ broker_roles: {} }), 'Not connected');
  assert.equal(brokersState({}), 'Not connected');
});

test('guardrailsState: a zero limit is not shown as 0 a day', () => {
  assert.equal(guardrailsState({ guardrails_enabled: false, daily_loss_limit: 5000 }), 'Off');
  assert.equal(guardrailsState({ guardrails_enabled: true, daily_loss_limit: 5000 }), 'On · ₹5,000/day');
  assert.equal(guardrailsState({ guardrails_enabled: true, daily_loss_limit: 0 }), 'On · no daily limit');
});

test('portfolio, telegram, model, autopilot', () => {
  assert.equal(portfolioState({ portfolio_max_loss_pct: 25, portfolio_max_weight_pct: 20 }), 'Max loss 25% · weight 20%');
  assert.equal(telegramState({ linked: true }), 'Linked');
  assert.equal(telegramState({}), 'Not linked');
  assert.equal(modelState({ omniroute_model: null }), 'Default');
  assert.equal(modelState({ omniroute_model: 'x/y' }), 'x/y');
  assert.equal(autopilotState({}), 'Off');
  assert.equal(autopilotState({ autopilot_enabled: true }), 'On · paper');
  assert.equal(autopilotState({ autopilot_enabled: true, autopilot_live: true }), 'On · live');
});

test('goalState', () => {
  assert.equal(goalState({ goal: null }), 'Not set');
  assert.equal(goalState({ goal: { kind: 'beat_nifty', target: 2, by: '2027-03-31' } }), 'Beat NIFTY by Mar 2027');
  assert.equal(goalState({ goal: { kind: 'value', target: 2500000, by: '2027-12-31' } }), '₹25,00,000 by Dec 2027');
});

test('NEWS_ALERTS', () => {
  assert.deepEqual(NEWS_ALERTS.map(([k]) => k), ['held', 'held+watched', 'all', 'off']);
});
