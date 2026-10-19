import { inr, pct, tone } from '../components/ui/format.js';

/**
 * The AI scoreboard from GET /today `scoreboard.month` ({mine, ai}) and
 * GET /analytics/scorecard (paper). Either may be missing; its figures show "—".
 * Percent fields in the scorecard are already percents (12.5 = 12.5%).
 */
export const scoreboard = ({ month, card } = {}) => {
  const t = card?.totals;
  const p = (v, sign) => (v == null ? '—' : pct(v / 100, { sign, dp: 1 }));
  return {
    versus: [
      { label: 'AI', value: inr(month?.ai, { sign: true }), tone: tone(month?.ai) },
      { label: 'You', value: inr(month?.mine, { sign: true }), tone: tone(month?.mine) },
      { label: 'NIFTY', value: p(card?.nifty_return_pct, true), tone: tone(card?.nifty_return_pct) },
    ],
    stats: [
      { label: 'Win rate', value: t ? pct(t.win_rate, { dp: 0 }) : '—' },
      { label: 'Trades', value: t ? String(t.trades) : '—' },
      { label: 'Charges', value: t ? inr(t.costs) : '—' },
      { label: 'Max drawdown', value: t ? p(t.max_drawdown_pct) : '—', tone: t?.max_drawdown > 0 ? 'loss' : 'neutral' },
    ],
  };
};
