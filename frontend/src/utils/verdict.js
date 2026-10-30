/** The Stock page's verdict card: the figure behind each rule (backend/portfolio/rules.py) and the key numbers.
 *  `f` is the verdict's `facts` (pnl_pct/weight_pct/nifty_pnl_pct in percent; trend prices in ₹; roe and
 *  revenue_growth as fractions; quarterly_profit in ₹, newest first). */

const n = (x) => typeof x === 'number' && Number.isFinite(x);
const rs = (x) => `₹${x.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const p1 = (x, sign = false) => `${x < 0 ? '−' : sign && x > 0 ? '+' : ''}${Math.abs(x).toFixed(1)}%`;
const crore = (x) => `₹${(x / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
const gap = (a, b) => p1(Math.abs(((a - b) / b) * 100));

/** One line with the numbers that made `code` fire, or null when they are missing. */
export const reasonFact = (code, f = {}, limits = {}) => {
  const q = (f.quarterly_profit || []).slice(0, 4).reverse(); // oldest first, as read
  switch (code) {
    case 'loss_beyond_limit':
      return n(f.pnl_pct) ? `Down ${p1(Math.abs(f.pnl_pct))} from your cost${n(limits.max_loss_pct) ? `; your limit is ${limits.max_loss_pct}%` : ''}` : null;
    case 'below_200dma':
      return n(f.close) && n(f.sma_200) ? `${rs(f.close)} against ${rs(f.sma_200)}, ${gap(f.close, f.sma_200)} below` : null;
    case 'uptrend':
      return n(f.close) && n(f.sma_50) && n(f.sma_200) ? `${rs(f.close)} > 50-day ${rs(f.sma_50)} > 200-day ${rs(f.sma_200)}` : null;
    case 'overweight':
      return n(f.weight_pct) ? `${p1(f.weight_pct)} of your portfolio${n(limits.max_weight_pct) ? `; your limit is ${limits.max_weight_pct}%` : ''}` : null;
    case 'high_debt':
      return n(f.debt_to_equity) ? `Debt/equity ${f.debt_to_equity.toFixed(2)}` : null;
    case 'strong_roe':
      return n(f.roe) ? `ROE ${p1(f.roe * 100)}` : null;
    case 'reasonable_valuation':
      return n(f.pe) ? `P/E ${f.pe.toFixed(1)}` : null;
    case 'earnings_falling_3q':
    case 'earnings_rising_3q':
      return q.length >= 2 && q.every(n) ? `Quarterly profit ${q.map(crore).join(' → ')}` : null;
    default:
      return null;
  }
};

/** [label, value, tone] for the figures that are there. */
export const keyNumbers = (f = {}) => [
  n(f.below_high_pct) && ['From 52-week high', p1(-f.below_high_pct), 'loss'],
  n(f.return_3m_pct) && ['Last 3 months', p1(f.return_3m_pct, true), f.return_3m_pct < 0 ? 'loss' : 'gain'],
  n(f.pnl_pct) && n(f.nifty_pnl_pct) && ['You vs NIFTY', `${p1(f.pnl_pct, true)} vs ${p1(f.nifty_pnl_pct, true)}`,
    f.pnl_pct < f.nifty_pnl_pct ? 'loss' : 'gain'],
  n(f.pe) && ['P/E', f.pe.toFixed(1), 'neutral'],
  n(f.debt_to_equity) && ['Debt/equity', f.debt_to_equity.toFixed(2), 'neutral'],
  n(f.revenue_growth) && ['Revenue growth', p1(f.revenue_growth * 100, true), f.revenue_growth < 0 ? 'loss' : 'gain'],
].filter(Boolean);

/** Older notes name rules by code (`below_200dma`); the prompt no longer asks for that. */
export const plainNote = (note) =>
  (note || '').replace(/`(\w+)`/g, (_, c) => c.replace('200dma', '200-day average').replace(/_3q$/, '_3_quarters').replace(/_/g, ' '));
