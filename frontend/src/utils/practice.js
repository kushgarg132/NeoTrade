/**
 * Practice → Book: the practice money's figures for one period, net of
 * charges, from closed round trips. Periods follow the IST calendar.
 */
const IST_MS = 5.5 * 3600 * 1000;

// A naive timestamp from the API is UTC (Mongo stores UTC without a zone).
const toDate = (value) => new Date(typeof value === 'string' && !/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? `${value}Z` : value);
const istDay = (date) => new Date(date.getTime() + IST_MS).toISOString().slice(0, 10);

const inPeriod = (period, day, today) =>
  period === 'today' ? day === today : period === 'month' ? day.slice(0, 7) === today.slice(0, 7) : true;

const netOf = (trade) => (trade.realized_pnl || 0) - (trade.costs || 0);

export const periodSummary = (trades, period, now = new Date()) => {
  const today = istDay(now);
  const rows = trades
    .filter((t) => t.exit_at && inPeriod(period, istDay(toDate(t.exit_at)), today))
    .sort((a, b) => toDate(a.exit_at) - toDate(b.exit_at));
  let running = 0;
  const curve = rows.map((t) => {
    running += netOf(t);
    return { t: toDate(t.exit_at).toISOString(), net: Math.round(running * 100) / 100 };
  });
  const wins = rows.filter((t) => netOf(t) > 0).length;
  return {
    net: Math.round(running * 100) / 100,
    trades: rows.length,
    wins,
    winRate: rows.length ? wins / rows.length : null,
    curve,
  };
};
