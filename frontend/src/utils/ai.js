import { inr, pct, tone } from '../components/ui/format.js';

/**
 * The AI scoreboard from GET /today `scoreboard.month` ({mine, ai}) and
 * GET /analytics/scorecard (paper). Either may be missing; its figures show "—".
 * Percent fields in the scorecard are already percents (12.5 = 12.5%).
 */
export const scoreboard = ({ month, card, capital, mineValue } = {}) => {
  const t = card?.totals;
  const p = (v, sign) => (v == null ? '—' : pct(v / 100, { sign, dp: 1 }));
  // % of the capital each book works with, so AI, You and NIFTY read in one unit.
  const share = (v, base) => (v == null || !base ? '—' : pct(v / base, { sign: true, dp: 1 }));
  return {
    versus: [
      { label: 'AI', value: share(month?.ai, capital), tone: tone(month?.ai) },
      { label: 'You', value: share(month?.mine, mineValue), tone: tone(month?.mine) },
      { label: 'NIFTY', value: p(card?.nifty_return_pct, true), tone: tone(card?.nifty_return_pct) },
    ],
    niftyFrom: card?.totals?.first_day || null,
    stats: [
      { label: 'Win rate', value: t ? pct(t.win_rate, { dp: 0 }) : '—' },
      { label: 'Trades', value: t ? String(t.trades) : '—' },
      { label: 'Charges', value: t ? inr(t.costs) : '—' },
      { label: 'Max drawdown', value: t ? p(t.max_drawdown_pct) : '—', tone: t?.max_drawdown > 0 ? 'loss' : 'neutral' },
    ],
  };
};
