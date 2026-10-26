/**
 * Order-ticket props from a suggested trade: a holding row's AI action or a
 * rebalance trade (`{ symbol, suggested: trade }`). Null when there is
 * nothing to trade -- at target, skipped, or no suggestion.
 */
export const ticketFrom = (row) => {
  const s = row?.suggested;
  if (!s?.side) return null;
  return { symbol: row.symbol, side: s.side, quantity: s.quantity, limitPrice: Math.round(s.price * 100) / 100, lastPrice: row.last_price ?? s.price };
};

const detail = (err, fallback) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : fallback);

/**
 * Place a whole rebalance plan after the user's one batch-level double tap: sells first (they free the cash),
 * each a CNC limit order at the plan price, through the same propose → confirm → second-tap token as a ticket.
 * Stops at the first failure so nothing is bought when a sell did not go through. `post(url, body)` is api.post;
 * `onStep` gets the results so far after each order. Returns `[{ symbol, side, quantity, status, note }]`, with
 * status `done`, `failed` (nothing placed), `unknown` (no answer: may be placed) or `skipped` (not tried).
 */
export const executeAll = async (trades, post, endpoints, onStep = () => {}) => {
  const ordered = [...trades].sort((a, b) => (a.side === 'SELL' ? 0 : 1) - (b.side === 'SELL' ? 0 : 1));
  const out = ordered.map((t) => ({ symbol: t.symbol, side: t.side, quantity: t.quantity, status: 'skipped', note: null }));
  for (let i = 0; i < ordered.length; i += 1) {
    const t = ordered[i];
    let card;
    try {
      card = (await post(endpoints.orders.propose, {
        symbol: t.symbol, side: t.side, quantity: t.quantity, product: 'CNC', order_type: 'LIMIT',
        limit_price: Math.round(t.price * 100) / 100, venue: 'live',
      })).data;
    } catch (err) {
      out[i] = { ...out[i], status: 'failed', note: detail(err, 'Could not check this order.') };
      onStep([...out]);
      return out;
    }
    try {
      let res = (await post(endpoints.chat.confirm(card.id), { confirm_token: null })).data;
      if (res.status === 'NEEDS_SECOND_TAP') res = (await post(endpoints.chat.confirm(card.id), { confirm_token: res.confirm_token })).data;
      out[i] = { ...out[i], status: 'done', note: res.result || null };
    } catch (err) {
      // No response at all: the order may be placed. Never say it was not.
      out[i] = err?.response
        ? { ...out[i], status: 'failed', note: detail(err, 'The order was not placed.') }
        : { ...out[i], status: 'unknown', note: 'No answer from the server: check Journal before trying again.' };
      onStep([...out]);
      return out;
    }
    onStep([...out]);
  }
  return out;
};
