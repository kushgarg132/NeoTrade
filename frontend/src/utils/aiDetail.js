/** Pure helpers for the AI strategy and trade pages. */

/** The scorecard row for one strategy, or null when it has no trades yet. */
export const strategyRow = (card, name) => (card?.strategies || []).find((s) => s.strategy === name) || null;

/** Parked wins, then paused (autopilot.paused names), then the forward proven badge. */
export const strategyStatus = ({ row, badge, paused, name }) => {
  if (row?.parked) return { label: 'Parked', tone: 'neutral' };
  if (name && (paused || []).includes(name)) return { label: 'Paused', tone: 'loss' };
  return badge?.tone === 'success' ? { label: 'Proven', tone: 'success' } : { label: 'Unproven', tone: 'neutral' };
};

const heldFor = (from, to) => {
  if (!from) return '–';
  const mins = Math.max(0, Math.round(((to ? new Date(to) : new Date()) - new Date(from)) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d`;
};

/** net = realized - costs only once closed; an open trade has no net yet. */
export const tradeSummary = (t) => {
  const open = t?.status === 'OPEN';
  const costs = t?.costs || 0;
  const gross = open ? null : t?.realized_pnl ?? 0;
  return { open, gross, costs, net: open ? null : gross - costs, held: heldFor(t?.entry_at, t?.exit_at) };
};

/** symbol -> id of its open trade, from GET /trading/trades?status=OPEN. A symbol with none is absent (callers fall back to the stock). */
export const openTradeIds = (trades) => Object.fromEntries((trades || []).filter((t) => t.status === 'OPEN' && t.id != null).map((t) => [t.symbol, t.id]));
