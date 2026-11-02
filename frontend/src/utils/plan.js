// The AI account's daily plan (GET /plan/today), for the plan card.

export const pct = (value, digits = 1) => {
  const n = Number(value || 0) * 100;
  return `${n < 0 ? '−' : '+'}${Math.abs(n).toFixed(digits)}%`;
};

/** One-line headline: risk-on/off and how many trades today. */
export const headline = (plan) => {
  if (!plan) return '';
  if (plan.risk_off) return 'Risk-off: the book sits in cash';
  const moves = (plan.buys?.length || 0) + (plan.sells?.length || 0);
  return moves ? `${moves} trade${moves === 1 ? '' : 's'} today · ${plan.holdings?.length || 0} held`
    : `Holding ${plan.holdings?.length || 0} · no trades today`;
};
