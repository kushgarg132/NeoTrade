import { inr, pct, tone } from '../components/ui/format.js';
import { holdingActions } from './ideas.js';
import { asOf } from './formatters.js';
import { digestLines } from './todayLayout.js';
import { summaryLines } from './summaries.js';

const REGIME = { risk_off: 'Risk off', risk_on: 'Risk on', neutral: 'Neutral' };
const PHASE = { pre: 'Before the open', session: 'Market open', post: 'After the close', closed: 'Market closed' };

export const phaseLabel = (phase) => PHASE[phase] || PHASE.session;

// /today and /mine/overview give percents as 1.65 (= 1.65%); format.js wants fractions.
const p100 = (x, opts) => (typeof x === 'number' ? pct(x / 100, opts) : '—');

/**
 * The four Home tiles' headline, sub-line and tone from GET /today, GET /mine/overview
 * and (optional) GET /market/indices. Any part may be missing: that tile shows "—".
 * `need` is the useNeedCount result ({ count, actions, ideas }, null while loading) and `book` the
 * AI page's figures (utils/ai.js::aiBook), so the tiles read what their pages show.
 */
export const tileHeadlines = (today, overview, indices, need = null, book = null, now = Date.now()) => {
  const t = today || {};
  const phase = t.phase || 'session';
  const day = phase === 'session' ? 'today' : 'last session'; // before the open the change is yesterday's
  const h = overview?.headline;
  const pulse = t.pulse;
  const money = h || pulse
    ? {
        value: inr((h || pulse).value),
        sub: `${day} ${p100((h || pulse).day_change_pct, { sign: true })}`,
        tone: 'neutral', // the value is a balance, not a delta
        subTone: tone((h || pulse).day_change),
        meta: asOf((h || pulse).as_of, phase, now),
      }
    : { value: '—', sub: 'Not read yet', tone: 'neutral' };

  const review = need ? holdingActions(need.actions).length : 0;
  const ideas = need
    ? { value: String(need.count), sub: `${review} to review · ${need.ideas.length} idea${need.ideas.length === 1 ? '' : 's'}`, tone: review ? 'warn' : 'neutral' }
    : { value: '—', sub: 'Unavailable', tone: 'neutral' };

  const ai = book && book.value != null
    ? { value: inr(book.value), sub: `${day} ${inr(book.day, { sign: true })} (${pct(book.dayPct, { sign: true })})`, tone: 'neutral', subTone: tone(book.day) }
    : { value: '—', sub: 'No AI book yet', tone: 'neutral' };

  const nifty = (Array.isArray(indices) ? indices : []).find((r) => r.name === 'NIFTY 50');
  const regime = REGIME[t.backdrop?.regime?.label];
  const market = nifty && typeof nifty.percent === 'number'
    ? { value: p100(nifty.percent, { sign: true }), sub: regime ? `NIFTY · ${regime}` : 'NIFTY', tone: tone(nifty.percent), meta: asOf(nifty.at, phase, now) }
    : { value: regime || '—', sub: 'NIFTY unavailable', tone: 'neutral' };

  return { money, ideas, ai, market };
};

/** Which /today digest Home shows: pre-market before the open, post-close after it, none in session. */
export const briefKind = (phase) => (phase === 'pre' ? 'premarket' : phase === 'post' || phase === 'closed' ? 'postclose' : null);

/** The weekly-report link shows Sunday and Monday (IST). */
export const showWeekly = (now = new Date()) => {
  const day = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' })).getDay();
  return day === 0 || day === 1;
};

/** One "what news moved your money" row's reason: the headline, else whether it just followed NIFTY
 * (within 2% of it, as backend/portfolio/news_moves.py::BIG_PCT). */
export const newsWhy = (m) => {
  if (m?.cause) return m.cause.title || '';
  return m?.vs_nifty != null && Math.abs(m.vs_nifty) < 2 ? 'Moved with the market' : 'No news found';
};

const BROKERS = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

/** What on Home needs attention right now: a broker login that expired, the kill switch, live money armed. */
export const alerts = (today) => {
  const t = today || {};
  const out = [];
  for (const [role, info] of Object.entries(t.accounts || {})) {
    if (info?.state !== 'ACTIVE') {
      out.push({ id: `login-${role}`, text: `${BROKERS[info.broker] || info.broker || 'Broker'}${role === 'ai' ? ' (AI)' : ''} login expired`, to: '/settings/brokers', login: info.broker, action: 'Log in' });
    }
  }
  if (t.kill_switch?.tripped) out.push({ id: 'kill', text: 'Daily loss limit hit: live trading stopped', to: '/ai', action: 'See AI' });
  const armed = t.live_armed;
  if (armed?.autopilot || armed?.strategies?.length) {
    out.push({ id: 'live', text: `Live money armed${armed.autopilot ? ': autopilot' : ''}${armed.strategies?.length ? ` · ${armed.strategies.length} strateg${armed.strategies.length === 1 ? 'y' : 'ies'}` : ''}`, to: '/ai', action: 'Stop', danger: true });
  }
  return out;
};

export const todayTitle = (kind) => (kind === 'premarket' ? 'Before the open' : kind === 'postclose' ? 'After the close' : 'Today');

/** The brief under the Today card: the AI's lines when a job wrote them, else the digest's after its own title line. */
export const briefLines = (text, summary) => {
  if (!text) return { ai: false, lines: [] };
  const ai = summaryLines(summary?.text);
  // The digest's "Your account: ₹…, today …" line repeats Home's hero, so it is left out here.
  return ai.length ? { ai: true, lines: ai } : { ai: false, lines: digestLines(text).slice(1).filter((l) => !/^Your account:/.test(l)) };
};

/** Your day against NIFTY in words: { gap (points), text } — "2.5 pts behind NIFTY", "level with NIFTY"; null without
 *  both. Percents as 1.65 (= 1.65%). */
export const vsNifty = (mine, nifty) => {
  if (typeof mine !== 'number' || typeof nifty !== 'number') return null;
  const gap = mine - nifty;
  if (Math.abs(gap) < 0.05) return { gap: 0, text: 'level with NIFTY' };
  return { gap, text: `${Math.abs(gap).toFixed(1)} pts ${gap > 0 ? 'ahead of' : 'behind'} NIFTY` };
};

/** "opens Mon 09:15" from /today's next_open (an IST ISO string); null without one. */
export const nextOpenLabel = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const f = (o) => d.toLocaleString('en-IN', { ...o, timeZone: 'Asia/Kolkata' });
  return `opens ${f({ weekday: 'short' })} ${f({ hour: '2-digit', minute: '2-digit', hour12: false })}`;
};
