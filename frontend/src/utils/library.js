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

const STRATEGY_NAMES = {
  orb_breakout: 'Opening-range breakout',
  orb_options: 'Opening-range options',
  gap_and_go: 'Gap and go',
  gap_fill_fade: 'Gap-fill fade',
  relative_strength_sector: 'Sector strength',
  vwap_reversion: 'VWAP reversion',
  rsi_momentum_scalp: 'RSI momentum scalp',
  macd_crossover: 'MACD crossover',
  trend_day_pullback: 'Trend-day pullback',
  cash_secured_put: 'Cash-secured put',
};

/** A strategy or rule code as a trader reads it: "orb_breakout" -> "Opening-range breakout". */
export const strategyName = (code) =>
  code ? STRATEGY_NAMES[code] || `${code.charAt(0).toUpperCase()}${code.slice(1).replace(/_/g, ' ')}` : code;
