import React from 'react';
import { Sheet, Statement, Row, Cell } from '../doc/Doc';
import { formatCurrency, formatPercent, formatSignedPercent } from '../../utils/formatters';
import { cn } from '../../utils/cn';

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
      <div className="relative h-1.5 bg-[var(--paper-sunk)]" aria-hidden="true">
        <div className="absolute top-1/2 -translate-y-1/2 w-2 h-3 bg-[var(--ink)]" style={{ left: `calc(${at}% - 4px)` }} />
      </div>
      <div className="mt-1 flex justify-between doc-meta normal-case">
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
    ['Support', formatCurrency(t?.support, currency), fromPrice(t?.support, price)],
    ['Resistance', formatCurrency(t?.resistance, currency), fromPrice(t?.resistance, price)],
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
    <Sheet title="Trading levels">
      <p className="field-label mb-1.5">52-week range</p>
      <RangeBar low={t?.low_52w} high={t?.high_52w} price={price} currency={currency} />
      <Statement
        inline
        className="mt-3"
        columns={[
          { key: 'item', label: 'Level' },
          { key: 'value', label: 'Value', align: 'right' },
          { key: 'note', label: 'Note', align: 'right' },
        ]}
      >
        {rows.map(([label, value, note]) => (
          <Row key={label}>
            <Cell className="text-[var(--ink-soft)]">{label}</Cell>
            <Cell align="right" mono>{value}</Cell>
            <Cell
              align="right"
              mono
              data-label={note ? undefined : ''}
              className={cn('text-[var(--ink-faint)]', note.startsWith('+') && 'text-up', note.startsWith('−') && 'text-down')}
            >
              {note}
            </Cell>
          </Row>
        ))}
      </Statement>
    </Sheet>
  );
};

export default TradingLevels;
