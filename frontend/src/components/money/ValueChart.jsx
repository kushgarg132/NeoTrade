import React, { useCallback, useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import { inr, compactInr } from '../ui/format';
import api, { endpoints } from '../../utils/api';
import { RANGES, rangeLabel, floorAtZero } from '../../utils/mine';
import { cn } from '../../utils/cn';
import { AXIS, GRID } from '../ui/chartTheme';

// Identity is never colour alone: the series also differ in dash and are named in the legend.
const SERIES = [
  { key: 'value', label: 'Your money', color: 'var(--accent)', dash: undefined },
  { key: 'nifty_value', label: 'Same money in NIFTY', color: 'var(--text-muted)', dash: '2 3' },
  { key: 'invested', label: 'Put in', color: 'var(--border)', dash: '5 4' },
];
const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });

const Tip = ({ active, payload, label }) =>
  active && payload?.length ? (
    <div className="rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[13px] space-y-0.5">
      <p className="text-[var(--text-muted)]">{short(label)}</p>
      {SERIES.map((s) => {
        const p = payload.find((x) => x.dataKey === s.key);
        return p && p.value != null ? (
          <p key={s.key} className="flex justify-between gap-4 tabular-nums">
            <span className="text-[var(--text-muted)]">{s.label}</span>
            <span className="private text-[var(--text)]">{inr(p.value)}</span>
          </p>
        ) : null;
      })}
    </div>
  ) : null;

/** Your value against NIFTY on the same rupees, with what went in. GET /mine/history. */
const ValueChart = () => {
  const [range, setRange] = useState('1Y');
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    let live = true;
    api.get(endpoints.mine.history(range)).then((res) => live && (setData(res.data), setFailed(false))).catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [range]);
  useEffect(() => load(), [load]);

  const points = data?.points || [];
  const chips = (
    <div className="flex gap-1" role="group" aria-label="Range">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={r === range}
          onClick={() => { setData(null); setRange(r); }}
          className={cn(
            'min-h-11 min-w-11 px-2 rounded-[12px] text-[14px] font-medium',
            r === range ? 'bg-[var(--surface-2)] text-[var(--text)]' : 'text-[var(--text-muted)]'
          )}
        >
          {rangeLabel(r)}
        </button>
      ))}
    </div>
  );

  return (
    <Card title="Value vs NIFTY" action={chips}>
      {failed ? (
        <ErrorLine message="Could not load the chart." onRetry={() => { setFailed(false); load(); }} />
      ) : !data ? (
        <Skeleton rows={5} />
      ) : points.length < 2 ? (
        <Empty title="Not enough history yet" body="The chart builds up from your imported trades, one point a trading day." />
      ) : (
        <>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 mb-2 text-[13px] text-[var(--text-muted)]">
            {SERIES.map((s) => (
              <li key={s.key} className="inline-flex items-center gap-1.5">
                <svg width="22" height="6" aria-hidden="true">
                  <line x1="0" y1="3" x2="22" y2="3" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} />
                </svg>
                {s.label}
              </li>
            ))}
          </ul>
          <div className="private h-56" role="img" aria-label={`Value ${inr(points.at(-1).value)} against ${inr(points.at(-1).invested)} put in, ${rangeLabel(range)}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis {...AXIS} dataKey="date" tickFormatter={short} minTickGap={40} />
                <YAxis {...AXIS} tickFormatter={compactInr} width={56} axisLine={false} domain={[floorAtZero, 'auto']} />
                <Tooltip content={<Tip />} />
                {SERIES.map((s) => (
                  <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={s.key === 'value' ? 2.5 : 2} strokeDasharray={s.dash} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {data.partial && <p className="text-[13px] text-[var(--text-muted)] mt-2">History is still filling in; earlier days may be missing.</p>}
        </>
      )}
    </Card>
  );
};

export default ValueChart;
