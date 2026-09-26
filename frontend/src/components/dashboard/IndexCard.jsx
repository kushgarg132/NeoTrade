import React, { useMemo, useState } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import { Sheet, Field, Empty, Ruling } from '../doc/Doc';
import { formatLevel, formatSignedPercent, formatNoteDate } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * One index, opened from the statement's index table: its level and day
 * change, a year of closes, the 52-week range and where it sits against its
 * 50- and 200-day averages. Levels are points, never rupees.
 */

const RANGES = [
  { id: '1M', days: 22 },
  { id: '3M', days: 66 },
  { id: '6M', days: 132 },
  { id: '1Y', days: 400 },
];

const CloseTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="sheet px-3 py-2 text-xs">
      <p className="doc-meta">{formatNoteDate(new Date(point.date))}</p>
      <p className="figure-md mt-1">{formatLevel(point.close)}</p>
    </div>
  );
};

const versus = (value, average) =>
  average ? `${value >= average ? 'Above' : 'Below'} by ${formatSignedPercent(((value - average) / average) * 100)}` : null;

const IndexCard = ({ detail, loading, error }) => {
  const [range, setRange] = useState('1Y');
  const points = useMemo(() => {
    const days = RANGES.find((item) => item.id === range).days;
    return (detail?.points || []).slice(-days);
  }, [detail, range]);

  if (loading) {
    return (
      <Sheet title="Index">
        <Ruling rows={5} />
      </Sheet>
    );
  }
  if (error || !detail) {
    return (
      <Sheet title="Index">
        <Empty title="Could not load this index" detail={error || 'The data provider did not respond.'} />
      </Sheet>
    );
  }

  const up = detail.change >= 0;
  const rising = points.length > 1 && points[points.length - 1].close >= points[0].close;
  const ink = rising ? 'var(--gain)' : 'var(--loss)';

  return (
    <Sheet title={detail.name} meta={detail.symbol}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="figure-lg">{formatLevel(detail.value)}</span>
        <span className={cn('figure-md text-base whitespace-nowrap', up ? 'text-up' : 'text-down')}>
          {up ? '+' : '−'}
          {formatLevel(Math.abs(detail.change))} ({formatSignedPercent(detail.percent)})
        </span>
      </div>
      <p className="doc-meta normal-case mt-1">Day change against the previous close</p>

      <div className="mt-4 flex border border-[var(--rule-strong)] w-fit" role="tablist" aria-label="Chart range">
        {RANGES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={range === item.id}
            onClick={() => setRange(item.id)}
            className={cn(
              'px-3 min-h-9 font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
              range === item.id ? 'bg-[var(--ink)] text-[var(--paper)]' : 'text-[var(--ink-soft)] hover:text-[var(--ink)]'
            )}
          >
            {item.id}
          </button>
        ))}
      </div>

      <div className="h-56 mt-3 -mx-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <defs>
              <linearGradient id="index-ink" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={ink} stopOpacity={0.2} />
                <stop offset="100%" stopColor={ink} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" hide />
            <YAxis
              width={58}
              domain={['auto', 'auto']}
              tick={{ fontSize: 10, fill: 'var(--ink-faint)' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => Math.round(value).toLocaleString('en-IN')}
            />
            <Tooltip content={<CloseTooltip />} cursor={{ stroke: 'var(--rule-strong)' }} />
            <Area
              type="monotone"
              dataKey="close"
              stroke={ink}
              strokeWidth={1.5}
              fill="url(#index-ink)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 pt-3 border-t border-[var(--rule)]">
        <Field label="52-week high" value={formatLevel(detail.high_52w)} />
        <Field label="52-week low" value={formatLevel(detail.low_52w)} />
        <div>
          <Field label="50-day average" value={formatLevel(detail.sma_50)} />
          <p className="doc-meta normal-case mt-1">{versus(detail.value, detail.sma_50)}</p>
        </div>
        <div>
          <Field label="200-day average" value={formatLevel(detail.sma_200)} />
          <p className="doc-meta normal-case mt-1">{versus(detail.value, detail.sma_200)}</p>
        </div>
      </div>
    </Sheet>
  );
};

export default IndexCard;
