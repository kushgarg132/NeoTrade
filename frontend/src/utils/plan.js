// Today's AI game plan (GET /plan/today), for the plan card.

const LABELS = {
  pre_open: 'Pre-open plan', regime_flip: 'Regime change', event_passed: 'Event passed',
  fallback: 'Fallback (AI unavailable)',
};

export const triggerLabel = (trigger) => {
  if (!trigger) return '';
  if (trigger.startsWith('news:')) return 'News';
  return LABELS[trigger] || trigger;
};

const rupees = (value) => {
  const n = Math.round(value || 0);
  return `₹${n < 0 ? '−' : '+'}${Math.abs(n).toLocaleString('en-IN')}`;
};

/** "Plan ₹+1,240 vs no plan ₹+310 over 5 days" from nightly replay scorecards. */
export const scoreLine = (cards) => {
  if (!cards?.length) return '';
  const sum = (side) => cards.reduce((total, c) => total + (c[side]?.net || 0), 0);
  return `Plan ${rupees(sum('a'))} vs no plan ${rupees(sum('b'))} over ${cards.length} day${cards.length === 1 ? '' : 's'}`;
};

export const allowSummary = (plan) => (plan?.allow || []).map(({ symbol, strategies }) => ({ symbol, strategies }));
