import { inr } from '../components/ui/format.js';

const DASH = '–';
const BROKERS = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };
const ROLES = { mine: 'yours', ai: 'AI' };

const TAB_PAGES = {
  accounts: '/settings/brokers', broker: '/settings/brokers',
  limits: '/settings/guardrails', portfolio: '/settings/guardrails', safety: '/settings/guardrails', guardrails: '/settings/guardrails',
  alerts: '/settings/notifications', profile: '/settings/profile', ai: '/settings/ai', goal: '/settings/goal',
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

export const brokersState = (prefs) => {
  if (!prefs) return DASH;
  const roles = Object.entries(prefs.broker_roles || {});
  if (!roles.length) return 'Not connected';
  return roles.map(([b, r]) => `${BROKERS[b] || b}: ${ROLES[r] || r}`).join(' · ');
};

export const guardrailsState = (prefs) => {
  if (!prefs) return DASH;
  if (!prefs.guardrails_enabled) return 'Off';
  return prefs.daily_loss_limit > 0 ? `On · ${inr(prefs.daily_loss_limit)}/day` : 'On · no daily limit';
};

export const portfolioState = (prefs) => (prefs
  ? `Max loss ${prefs.portfolio_max_loss_pct}% · weight ${prefs.portfolio_max_weight_pct}%` : DASH);

export const telegramState = (t) => (t?.linked ? 'Linked' : t ? 'Not linked' : DASH);

const month = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });

export const goalState = (prefs) => {
  if (!prefs) return DASH;
  const g = prefs.goal;
  if (!g) return 'Not set';
  return g.kind === 'value' ? `${inr(g.target)} by ${month(g.by)}` : `Beat NIFTY by ${month(g.by)}`;
};

export const modelState = (prefs) => (prefs ? prefs.omniroute_model || 'Default' : DASH);

export const autopilotState = (prefs) => {
  if (!prefs) return DASH;
  return prefs.autopilot_enabled ? `On · ${prefs.autopilot_live ? 'live' : 'paper'}` : 'Off';
};

export const NEWS_ALERTS = [['held', 'Held'], ['held+watched', 'Held + watched'], ['all', 'All'], ['off', 'Off']];
