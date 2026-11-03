// The AI account's daily plan (GET /plan/today), for the plan card.

export const pct = (value, digits = 1) => {
  const n = Number(value || 0) * 100;
  return `${n < 0 ? '−' : n > 0 ? '+' : ''}${Math.abs(n).toFixed(digits)}%`;
};

/** One-line headline: risk-on/off and how many trades today. */
export const headline = (plan) => {
  if (!plan) return '';
  if (plan.risk_off) return `Risk-off: Nifty ${pct(plan.nifty_vs_200dma)} vs its 200-day average, so no buys. Next check ${plan.next_rebalance}`;
  const moves = (plan.buys?.length || 0) + (plan.sells?.length || 0);
  return moves ? `${moves} trade${moves === 1 ? '' : 's'} today · ${plan.holdings?.length || 0} held`
    : `Holding ${plan.holdings?.length || 0} · no trades today`;
};

/** The scorecard's three lines on one scale (AI book, NIFTY, Momentum 30 ETF), skipping a missing one. */
export const versusRows = (card) => [
  ['AI', card?.book], ['NIFTY', card?.nifty], ['Mom 30', card?.mom30],
].filter(([, r]) => typeof r === 'number').map(([label, r]) => ({
  label, pct: r * 100, value: pct(r), tone: r > 0 ? 'gain' : r < 0 ? 'loss' : 'neutral',
}));

/** One line on the live gate: ready, ahead and waiting for the date, or behind. */
export const gateLine = (card) => {
  if (!card) return '';
  if (card.live_ready) return 'Live gate met: three months ahead of the NIFTY. Going live is your call.';
  if (card.days === 0) return `Just started: nothing to compare yet. The earliest live date is ${card.unlock_on}.`;
  if (card.ahead) return `Ahead of the NIFTY. Live can be considered from ${card.unlock_on} if it stays ahead.`;
  return `Behind the NIFTY: stays on paper. The earliest live date is ${card.unlock_on}.`;
};

/** "3 of 5 vetoed names did worse than the book" or '' with no scored veto yet. */
export const vetoLine = (v) => (v?.n ? `${v.helped} of ${v.n} names news kept out did worse than the book (${pct(v.vetoed_avg)} vs ${pct(v.book_avg)}).` : '');
