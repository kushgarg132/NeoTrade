/** The Stock page's Events tab: names, countdowns and payouts for corporate events (mine/events.py). */

const TITLE = { results: 'Quarterly results', ex_dividend: 'Ex-dividend' };

export const eventTitle = (e) => TITLE[e.kind] || String(e.label || e.type || e.kind || 'Event').replace(/_/g, ' ');

/** Whole days from `today` (YYYY-MM-DD, IST) to `date` (YYYY-MM-DD). */
export const daysUntil = (date, today) => Math.round((Date.parse(date) - Date.parse(today)) / 86_400_000);

export const countdown = (n) => (n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n > 1 ? `In ${n} days` : `${-n} days ago`);

/** Today in IST as YYYY-MM-DD. */
export const todayIst = (now = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(now);

/** "Headline - Source" (how the AI read's event descriptions end) -> "Source"; null without one. */
export const sourceOf = (description) => {
  const i = (description || '').lastIndexOf(' - ');
  return i > 0 ? description.slice(i + 3).trim() || null : null;
};

/** The dividend history, each row with what the user got that time (matched by ex-date), newest first,
 *  and the total they got. `past` per share from the stock's history; `received` from the journal. */
export const dividendRows = (past = [], received = []) => {
  const got = new Map(received.map((d) => [d.date, d]));
  const rows = past.map((d) => ({ date: d.date, perShare: d.per_share, qty: got.get(d.date)?.qty, amount: got.get(d.date)?.amount }));
  for (const d of received)
    if (!past.some((p) => p.date === d.date)) rows.push({ date: d.date, perShare: d.per_share, qty: d.qty, amount: d.amount });
  rows.sort((a, b) => b.date.localeCompare(a.date));
  return { rows, total: received.reduce((s, d) => s + (d.amount || 0), 0) };
};
