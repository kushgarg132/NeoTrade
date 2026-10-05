// The strategy library (GET /strategies/library), for the Library page.

/** 'paused' | 'untested' | 'live-ready' | 'paper' -- where a strategy stands for this account. */
export const statusOf = (card) => {
  if (card?.learned?.paused) return 'paused';
  if (!card?.backtest) return 'untested';
  return card.backtest.passed && card.paper?.passed ? 'live-ready' : 'paper';
};

const rupees = (value) => {
  const n = Math.round(value || 0);
  return `₹${n < 0 ? '−' : '+'}${Math.abs(n).toLocaleString('en-IN')}`;
};

/** "12 trades · win 58% · net ₹+3,200", or "No paper trades yet". */
export const recordLine = (card) => {
  const all = card?.stats?.all;
  if (!all || !all.trades) return 'No paper trades yet';
  return `${all.trades} trade${all.trades === 1 ? '' : 's'} · win ${Math.round((all.win_rate || 0) * 100)}% · net ${rupees(all.net)}`;
};
