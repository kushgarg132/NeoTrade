import React from 'react';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * One month of trading days as a grid of cells, each carrying that day's net
 * P&L. `byDay` maps "YYYY-MM-DD" to { pnl, trips }. Shared by the journal
 * (real broker trades) and the paper scorecard.
 */

const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

// Two significant figures: a day cell is ~45px wide on a phone, so "+18T"
// fits where "+18.42T" spills into the next day.
const cellFigure = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumSignificantDigits: 2 });

const MonthGrid = ({ month, byDay, selected, onSelect }) => {
  const [year, m] = month.split('-').map(Number);
  const first = new Date(Date.UTC(year, m - 1, 1));
  const days = new Date(Date.UTC(year, m, 0)).getUTCDate();
  const lead = (first.getUTCDay() + 6) % 7; // Monday-first

  const cells = [
    ...Array.from({ length: lead }, () => null),
    ...Array.from({ length: days }, (_, index) => `${month}-${String(index + 1).padStart(2, '0')}`),
  ];

  return (
    <div>
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((label, index) => (
          <span key={index} className="doc-meta text-center">
            {label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, index) => {
          if (!day) return <span key={`lead-${index}`} />;
          const row = byDay[day];
          const tone = !row || row.pnl === 0 ? '' : row.pnl > 0 ? 'text-up' : 'text-down';
          return (
            <button
              key={day}
              type="button"
              disabled={!row}
              onClick={() => onSelect(selected === day ? null : day)}
              aria-label={row ? `${day}: ${formatCurrency(row.pnl)}, ${row.trips} trades` : day}
              aria-pressed={selected === day}
              className={cn(
                'min-h-12 min-w-0 px-1 py-1 border text-left flex flex-col justify-between overflow-hidden',
                row ? 'border-[var(--rule-strong)]' : 'border-[var(--rule)] opacity-60',
                selected === day && 'border-[var(--stamp)] bg-[var(--paper-sunk)]'
              )}
            >
              <span className="doc-meta">{Number(day.slice(8))}</span>
              {row && (
                <span className={cn('figure-md text-[0.625rem] sm:text-[0.6875rem] leading-tight whitespace-nowrap', tone)}>
                  {row.pnl > 0 ? '+' : row.pnl < 0 ? '−' : ''}
                  {cellFigure.format(Math.abs(row.pnl))}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default MonthGrid;
