import React from 'react';
import Card from '../ui/Card';
import { formatCurrency, formatPercent, formatSignedPercent } from '../../utils/formatters';

const isNum = (value) => typeof value === 'number' && Number.isFinite(value);

/** % a level sits from the price: "+3.20%" above, "−1.10%" below. */
const fromPrice = (level, price) => (isNum(level) && isNum(price) && price ? formatSignedPercent((level / price - 1) * 100) : '—');

const rsiReading = (rsi) => (!isNum(rsi) ? '' : rsi > 70 ? 'overbought' : rsi < 30 ? 'oversold' : 'neutral');

const bollinger = (t) => {
  if (!isNum(t?.price) || !isNum(t?.bb_upper) || !isNum(t?.bb_lower)) return '—';
  if (t.price > t.bb_upper) return 'Above upper band';
  if (t.price < t.bb_lower) return 'Below lower band';
  return 'Inside bands';
};

/** Where the price sits in its 52-week range, as a bar. */
const RangeBar = ({ low, high, price, currency }) => {
  if (!isNum(low) || !isNum(high) || !isNum(price) || high <= low) return <span>—</span>;
  const at = Math.max(0, Math.min(100, ((price - low) / (high - low)) * 100));
  return (
    <div className="w-full">
      <div className="relative h-1.5 rounded-full bg-[var(--surface-2)]" aria-hidden="true">
        <div className="absolute top-1/2 -translate-y-1/2 w-2 h-3 rounded-sm bg-[var(--accent)]" style={{ left: `calc(${at}% - 4px)` }} />
      </div>
      <div className="mt-1 flex justify-between text-[13px] text-[var(--text-muted)]">
        <span>{formatCurrency(low, currency)}</span>
        <span>{formatCurrency(high, currency)}</span>
      </div>
    </div>
  );
};

/**
 * What a trader times an entry or exit on: the nearest levels, how far the
 * stock usually moves in a day, where it sits in its year, momentum and the
 * averages. Every figure reads "—" when the history could not support it.
 */
const TradingLevels = ({ t, currency }) => {
  const price = t?.price;
  const macdAbove = isNum(t?.macd) && isNum(t?.macd_signal) ? t.macd >= t.macd_signal : null;
  const rows = [
    // With a price but no level, the stock trades past every recent swing: say so.
    ['Support', formatCurrency(t?.support, currency), isNum(price) && !isNum(t?.support) ? 'none below price' : fromPrice(t?.support, price)],
    ['Resistance', formatCurrency(t?.resistance, currency), isNum(price) && !isNum(t?.resistance) ? 'none above price' : fromPrice(t?.resistance, price)],
    [
      'Typical daily move (ATR)',
      formatCurrency(t?.atr, currency),
      isNum(t?.atr) && isNum(price) && price ? formatPercent((t.atr / price) * 100) : '—',
    ],
    ['RSI (14)', isNum(t?.rsi) ? t.rsi.toFixed(1) : '—', rsiReading(t?.rsi)],
    ['MACD', isNum(t?.macd) ? t.macd.toFixed(2) : '—', macdAbove === null ? '' : macdAbove ? 'above signal' : 'below signal'],
    ['Bollinger (20, 2σ)', bollinger(t), ''],
    ['20-day EMA', formatCurrency(t?.ema_20, currency), fromPrice(t?.ema_20, price)],
    ['50-day average', formatCurrency(t?.sma_50, currency), fromPrice(t?.sma_50, price)],
    ['200-day average', formatCurrency(t?.sma_200, currency), fromPrice(t?.sma_200, price)],
  ];

  return (
    <Card title="Trading levels">
      <p className="text-[13px] text-[var(--text-muted)] mb-1.5">52-week range</p>
      <RangeBar low={t?.low_52w} high={t?.high_52w} price={price} currency={currency} />
      <ul className="mt-3">
        {rows.map(([label, value, note]) => (
          <li key={label} className="flex items-baseline gap-3 min-h-11 py-2 border-b border-[var(--border)] last:border-b-0 text-[15px]">
            <span className="flex-1 min-w-0 text-[var(--text-muted)]">{label}</span>
            <span className="private tabular-nums font-medium text-[var(--text)]">{value}</span>
            {note && <span className={`w-24 text-right text-[13px] tabular-nums ${note.startsWith('+') ? 'text-[var(--gain)]' : note.startsWith('−') ? 'text-[var(--loss)]' : 'text-[var(--text-muted)]'}`}>{note}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
};

export default TradingLevels;
