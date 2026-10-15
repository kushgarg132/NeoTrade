import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Sheet, Empty, Ruling } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { RANGES, rangeLabel } from '../../utils/mine';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';

// Identity is never colour alone: each series also differs in dash and is named in the legend.
const SERIES = [
  { key: 'value', label: 'Your value', color: 'var(--ink)', dash: undefined },
  { key: 'invested', label: 'Money put in', color: 'var(--ink-faint)', dash: '5 4' },
  { key: 'nifty_value', label: 'Same money in NIFTY', color: 'var(--stamp)', dash: '2 3' },
];

const compact = (v) => (v >= 1e7 ? `${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : `${Math.round(v / 1e3)}k`);
const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

const CurveTip = ({ active, payload, label }) =>
  active && payload?.length ? (
    <div className="sheet px-2.5 py-2 bg-[var(--paper)] text-xs space-y-0.5">
      <p className="field-label">{short(label)}</p>
      {SERIES.map((s) => {
        const p = payload.find((x) => x.dataKey === s.key);
        return p && p.value != null ? (
          <p key={s.key} className="flex justify-between gap-4">
            <span className="text-[var(--ink-soft)]">{s.label}</span>
            <span className="figure-md">{formatCurrency(p.value)}</span>
          </p>
        ) : null;
      })}
    </div>
  ) : null;

/** The account's value, what went in, and NIFTY on the same flows. GET /mine/history. */
const ValueCurve = () => {
  const [range, setRange] = useState('1Y');
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .get(endpoints.mine.history(range))
      .then((res) => live && (setData(res.data), setFailed(false)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [range]);

  const points = data?.points || [];
  const chips = (
    <div className="flex gap-1" role="group" aria-label="Range">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={r === range}
          onClick={() => setRange(r)}
          className={cn(
            'min-h-9 px-2.5 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em]',
            r === range ? 'border-[var(--ink)] text-[var(--ink)]' : 'border-[var(--rule-strong)] text-[var(--ink-faint)]'
          )}
        >
          {rangeLabel(r)}
        </button>
      ))}
    </div>
  );

  return (
    <Sheet title="Value over time" actions={chips}>
      {failed ? (
        <Empty title="Could not load the curve" />
      ) : !data ? (
        <Ruling rows={5} />
      ) : points.length < 2 ? (
        <Empty title="Not enough history yet" detail="The curve builds up from your imported trades, one point a trading day." />
      ) : (
        <>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 mb-2 text-xs text-[var(--ink-soft)]">
            {SERIES.map((s) => (
              <li key={s.key} className="inline-flex items-center gap-1.5">
                <svg width="22" height="6" aria-hidden="true">
                  <line x1="0" y1="3" x2="22" y2="3" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} />
                </svg>
                {s.label}
              </li>
            ))}
          </ul>
          <div className="h-56 sm:h-72" role="img" aria-label={`Value ${formatCurrency(points.at(-1).value)} against ${formatCurrency(points.at(-1).invested)} put in, ${rangeLabel(range)}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--rule)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={short} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} minTickGap={40} tickLine={false} axisLine={{ stroke: 'var(--rule-strong)' }} />
                <YAxis tickFormatter={compact} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} width={40} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
                <Tooltip content={<CurveTip />} />
                {SERIES.map((s) => (
                  <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={2} strokeDasharray={s.dash} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {data.partial && <p className="doc-meta normal-case mt-2">History is still filling in; earlier days may be missing.</p>}
        </>
      )}
    </Sheet>
  );
};

export default ValueCurve;
