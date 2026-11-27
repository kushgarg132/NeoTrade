import { ChevronDown } from 'lucide-react';
import React, { useState } from 'react';
import Card from '../ui/Card';
import { compactInr } from '../ui/format';
import { formatCompactNumber, formatCurrency, formatPercent } from '../../utils/formatters';

const isNum = (value) => typeof value === 'number' && Number.isFinite(value);
const ratio = (value) => (isNum(value) ? value.toFixed(2) : null);
const pct = (fraction) => (isNum(fraction) ? formatPercent(fraction * 100) : null);
const money = (value, currency) =>
  !isNum(value) ? null
    : currency === 'INR' ? `${value < 0 ? '−' : ''}${compactInr(Math.abs(value))}` // ₹18.6 lakh Cr, not en-IN compact's ₹18.64LCr
      : `${value < 0 ? '−' : ''}$${formatCompactNumber(Math.abs(value))}`;

/**
 * Whether the business is worth owning: valuation, profitability, and growth
 * and balance sheet. A missing figure prints "—"; a group with nothing in it
 * is left out (an ETF has no margins).
 */
const Fundamentals = ({ company: c, currency }) => {
  const net = isNum(c?.total_cash) && isNum(c?.total_debt) ? c.total_cash - c.total_debt : null;
  const groups = [
    [
      'Valuation',
      [
        ['Market cap', money(c?.market_cap, currency)],
        ['P/E', ratio(c?.pe_ratio)],
        ['PEG', ratio(c?.peg_ratio)],
        ['Price / book', ratio(c?.price_to_book)],
        ['EPS (trailing)', isNum(c?.trailing_eps) ? formatCurrency(c.trailing_eps, currency) : null],
        ['EPS (forward)', isNum(c?.forward_eps) ? formatCurrency(c.forward_eps, currency) : null],
        ['Dividend yield', pct(c?.dividend_yield)],
      ],
    ],
    [
      'Profitability',
      [
        ['Return on equity', pct(c?.return_on_equity)],
        ['Return on assets', pct(c?.return_on_assets)],
        ['Operating margin', pct(c?.operating_margins)],
        ['Gross margin', pct(c?.gross_margins)],
      ],
    ],
    [
      'Growth & balance sheet',
      [
        ['Revenue', money(c?.total_revenue, currency)],
        ['Revenue growth', pct(c?.revenue_growth)],
        ['EBITDA', money(c?.ebitda, currency)],
        ['Total debt', money(c?.total_debt, currency)],
        ['Total cash', money(c?.total_cash, currency)],
        [net === null || net >= 0 ? 'Net cash' : 'Net debt', money(net === null ? null : Math.abs(net), currency)],
        ['Beta', ratio(c?.beta)],
      ],
    ],
  ].filter(([, rows]) => rows.some(([, value]) => value !== null));

  // The six a trader reads first; every figure stays one tap away under "All fundamentals".
  const key = [
    ['Market cap', money(c?.market_cap, currency)],
    ['P/E', ratio(c?.pe_ratio)],
    ['Price / book', ratio(c?.price_to_book)],
    ['Return on equity', pct(c?.return_on_equity)],
    ['Revenue growth', pct(c?.revenue_growth)],
    [net === null || net >= 0 ? 'Net cash' : 'Net debt', money(net === null ? null : Math.abs(net), currency)],
  ].filter(([, v]) => v !== null);
  const [all, setAll] = useState(false);
  if (!groups.length) return null;
  return (
    <Card title="Fundamentals">
      {key.length > 0 && (
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4">
          {key.map(([label, value]) => (
            <div key={label} className="py-1.5 border-b border-[var(--border)] min-w-0">
              <dt className="text-[13px] text-[var(--text-muted)] truncate">{label}</dt>
              <dd className="tabular-nums text-[15px] font-medium text-[var(--text)]">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)}
        className="mt-1 inline-flex min-h-11 items-center gap-1 text-[14px] font-semibold text-[var(--accent)] rounded-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        {all ? 'Fewer figures' : 'All fundamentals'}
        <ChevronDown className={`w-4 h-4 transition-transform ${all ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {all && <div className="fade-in mt-2 grid gap-4 md:grid-cols-3">
        {groups.map(([title, rows]) => (
          // Behind "All fundamentals" (owner, 2026-11-27); each group still folds on tap.
          <details key={title} className="min-w-0 group" open>
            <summary className="text-[14px] font-semibold text-[var(--text)] cursor-pointer list-none flex items-center justify-between min-h-11 md:min-h-0">
              {title}
              <span className="text-[13px] font-normal text-[var(--text-muted)] inline-flex items-center gap-1" aria-hidden="true">
                {rows.length}
                <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" />
              </span>
            </summary>
            {/* Two figures a line: label over value, in a 2-column grid. */}
            <dl className="grid grid-cols-2 gap-x-4">
              {rows.map(([label, value]) => (
                <div key={label} className="py-1.5 border-b border-[var(--border)] min-w-0">
                  <dt className="text-[13px] text-[var(--text-muted)] truncate">{label}</dt>
                  <dd className="tabular-nums text-[15px] font-medium text-[var(--text)]">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </details>
        ))}
      </div>}
    </Card>
  );
};

export default Fundamentals;
