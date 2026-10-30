import { inr } from '../components/ui/format.js';

const BROKERS = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const TAB_PAGES = {
  accounts: '/settings/brokers', broker: '/settings/brokers',
  limits: '/settings/guardrails', portfolio: '/settings/portfolio', safety: '/settings/guardrails', guardrails: '/settings/guardrails',
  alerts: '/settings/notifications', profile: '/profile', ai: '/settings/ai', goal: '/settings/goal',
  theme: '/settings', lab: '/settings/lab', about: '/settings/lab', beta: '/settings/lab',
};

/** Old `/settings?tab=` -> new page; other params are kept. Null when there is no `tab`. */
export const settingsRedirect = (search) => {
  const params = new URLSearchParams(search);
  const tab = params.get('tab');
  if (tab === null) return null;
  params.delete('tab');
  const q = params.toString();
  return `${TAB_PAGES[tab] || '/settings'}${q ? `?${q}` : ''}`;
};

// A sentence is a list of parts: plain text, or a chip `{ v, tone?, private? }` holding a value.
const chip = (v, tone, priv) => ({ v, ...(tone && { tone }), ...(priv && { private: true }) });
const month = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const ROLE_NAME = { mine: 'your account', ai: 'AI account' };

/** A broker session as a word and a tone; `state` is BrokerSessionState from GET /today. */
export const SESSION = {
  ACTIVE: ['live', 'gain'], NEEDS_LOGIN: ['logged out', 'warn'], DEGRADED: ['expired', 'loss'], UNCONFIGURED: ['no API keys', 'warn'],
};

/** Each role's broker and session: GET /today `accounts` when it loaded, else prefs' roles without a state. */
export const accountsOf = (prefs, today) => {
  if (today?.accounts) return today.accounts;
  return Object.fromEntries(Object.entries(prefs?.broker_roles || {}).map(([broker, role]) => [role, { broker, state: null }]));
};

export const brokerName = (b) => BROKERS[b] || b;

/** What is broken, with its one fix: broker sessions, the kill switch, an unlinked Telegram. */
export const needsYou = ({ accounts, today, telegram }) => {
  const items = [];
  if (accounts && !Object.keys(accounts).length) items.push({ text: 'No broker connected', action: 'Connect', to: '/settings/brokers' });
  for (const role of ['mine', 'ai']) {
    const a = accounts?.[role];
    if (!a || !a.state || a.state === 'ACTIVE') continue;
    const name = `${brokerName(a.broker)} (${ROLE_NAME[role]})`;
    const to = `/settings/brokers?broker=${a.broker}`;
    if (a.state === 'DEGRADED') items.push({ text: `${name} session expired`, action: 'Reconnect', to, tone: 'loss' });
    else if (a.state === 'NEEDS_LOGIN') items.push({ text: `${name} is logged out`, action: 'Log in', to, tone: 'warn' });
    else items.push({ text: `${name} has no API keys`, action: 'Add keys', to, tone: 'warn' });
  }
  if (today?.kill_switch?.tripped) {
    items.push({ text: 'Daily loss limit hit: live trading stopped', action: 'See why', to: '/journal?tab=guardrails', tone: 'loss' });
  }
  if (telegram && !telegram.linked) items.push({ text: 'Telegram not linked: alerts reach only this app', action: 'Link', to: '/settings/notifications', tone: 'warn' });
  return items;
};

/** Sentences; null when their data did not load (the row then shows a dash). */
export const guardrailsLine = (p) => {
  if (!p) return null;
  if (!p.guardrails_enabled) return ['Guardrails are ', chip('off', 'warn'), '.'];
  const loss = p.daily_loss_limit > 0 ? ['stop you at ', chip(inr(p.daily_loss_limit)), ' lost a day'] : ['have ', chip('no daily limit', 'warn')];
  const trades = p.max_trades_per_day > 0 ? [' and ', chip(String(p.max_trades_per_day)), ' trades'] : [];
  return ['Guardrails ', ...loss, ...trades, '.'];
};

export const portfolioLine = (p) => (p
  ? ['Review flags a holding ', chip(`${p.portfolio_max_loss_pct}%`), ' under cost or over ', chip(`${p.portfolio_max_weight_pct}%`), ' of the whole.']
  : null);

export const goalLine = (p) => {
  if (!p) return null;
  const g = p.goal;
  if (!g) return ['No goal ', chip('set one'), '.'];
  return g.kind === 'value'
    ? ['Goal: ', chip(inr(g.target), null, true), ' by ', chip(month(g.by)), '.']
    : ['Goal: beat ', chip('NIFTY'), ' by ', chip(month(g.by)), '.'];
};

export const autopilotLine = (p) => {
  if (!p) return null;
  if (!p.autopilot_enabled) return ['Autopilot is ', chip('off'), '.'];
  return ['Autopilot trades on ', p.autopilot_live ? chip('live money', 'loss') : chip('paper'), ', news entries ', chip(p.autopilot_news ? 'on' : 'off'), '.'];
};

/** The deployment-wide Deep model (chat runs on it), else the fallback; provider prefix dropped. */
export const modelLine = (m) => {
  const id = m?.tiers?.deep || m?.fallback;
  return id ? ['AI answers with ', chip(id.split('/').pop()), '.'] : null;
};

const NEWS_WORDS = { held: 'held stocks', 'held+watched': 'held and watched stocks', all: 'every stock' };
export const alertsLine = (t, p) => {
  if (!t || !p) return null;
  const tg = t.linked ? chip('linked') : chip('not linked', 'warn');
  const news = NEWS_WORDS[p.news_alerts || 'held'];
  return ['Telegram ', tg, news ? '; news alerts for ' : '; news alerts ', chip(news || 'off'), '.'];
};

export const NEWS_ALERTS = [['held', 'Held'], ['held+watched', 'Held + watched'], ['all', 'All'], ['off', 'Off']];
