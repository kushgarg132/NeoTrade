import React from 'react';
import { Sheet } from '../doc/Doc';
import { formatCompactNumber, formatCurrency, formatPercent } from '../../utils/formatters';

const isNum = (value) => typeof value === 'number' && Number.isFinite(value);
const ratio = (value) => (isNum(value) ? value.toFixed(2) : null);
const pct = (fraction) => (isNum(fraction) ? formatPercent(fraction * 100) : null);
const money = (value, currency) =>
  isNum(value) ? `${value < 0 ? '−' : ''}${currency === 'INR' ? '₹' : '$'}${formatCompactNumber(Math.abs(value))}` : null;

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

  if (!groups.length) return null;
  return (
    <Sheet title="Fundamentals">
      <div className="grid gap-4 md:grid-cols-3">
        {groups.map(([title, rows], i) => (
          <details key={title} className="min-w-0 group" open={i === 0}>
            <summary className="field-label mb-1 cursor-pointer list-none flex items-center justify-between min-h-11 md:min-h-0">
              {title}
              <span className="doc-meta md:hidden" aria-hidden="true">{rows.length}</span>
            </summary>
            {/* Two figures a line: label over value, in a 2-column grid. */}
            <dl className="grid grid-cols-2 gap-x-4">
              {rows.map(([label, value]) => (
                <div key={label} className="py-1.5 border-b border-[var(--rule)] min-w-0">
                  <dt className="doc-meta normal-case truncate">{label}</dt>
                  <dd className="figure-md text-sm">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </details>
        ))}
      </div>
    </Sheet>
  );
};

export default Fundamentals;
