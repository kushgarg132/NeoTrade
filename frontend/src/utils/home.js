import { inr, pct, tone } from '../components/ui/format.js';

const EXIT_KINDS = ['stop_hit', 'target_hit', 'idea_exit'];
const REGIME = { risk_off: 'Risk off', risk_on: 'Risk on', neutral: 'Neutral' };
const PHASE = { pre: 'Before the open', session: 'Market open', post: 'After the close', closed: 'Market closed' };

export const phaseLabel = (phase) => PHASE[phase] || PHASE.session;

// /today and /mine/overview give percents as 1.65 (= 1.65%); format.js wants fractions.
const p100 = (x, opts) => (typeof x === 'number' ? pct(x / 100, opts) : '—');

/**
 * The four Home tiles' headline, sub-line and tone from GET /today, GET /mine/overview
 * and (optional) GET /market/indices. Any part may be missing: that tile shows "—".
 */
export const tileHeadlines = (today, overview, indices) => {
  const t = today || {};
  const h = overview?.headline;
  const pulse = t.pulse;
  const money = h || pulse
    ? {
        value: inr((h || pulse).value),
        sub: [`today ${p100((h || pulse).day_change_pct, { sign: true })}`,
          typeof h?.xirr === 'number' ? `XIRR ${pct(h.xirr, { dp: 1 })}` : null].filter(Boolean).join(' · '),
        tone: tone((h || pulse).day_change),
      }
    : { value: '—', sub: 'Not read yet', tone: 'neutral' };

  const n = t.proposals_total;
  const exits = (t.mine_actions || []).filter((a) => EXIT_KINDS.includes(a.kind)).length;
  const ideas = typeof n === 'number'
    ? { value: String(n), sub: `${n} proven · ${exits} exit`, tone: exits ? 'warn' : 'neutral' }
    : { value: '—', sub: 'Unavailable', tone: 'neutral' };

  const b = t.scoreboard;
  const ai = b
    ? { value: inr(b.today.ai, { sign: true }), sub: `month ${inr(b.month.ai, { sign: true })} · you ${inr(b.month.mine, { sign: true })}`, tone: tone(b.today.ai) }
    : { value: '—', sub: 'No AI book yet', tone: 'neutral' };

  const nifty = (indices || []).find((r) => r.name === 'NIFTY 50');
  const regime = REGIME[t.backdrop?.regime?.label];
  const market = nifty && typeof nifty.percent === 'number'
    ? { value: p100(nifty.percent, { sign: true }), sub: regime ? `NIFTY · ${regime}` : 'NIFTY', tone: tone(nifty.percent) }
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
