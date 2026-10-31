import React from 'react';
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';

/** A chart the assistant drew from real numbers (backend/chat/media.py::chart_spec). */
const COLORS = [1, 2, 3, 4, 5, 6].map((n) => `var(--chart-${n})`);
const BY_KIND = { line: [LineChart, Line], area: [AreaChart, Area], bar: [BarChart, Bar] };

const ChatChart = ({ spec }) => {
  const { title, kind, unit, labels, series } = spec;
  const fmt = (v) => (v == null ? '–' : unit === '₹' ? `₹${Number(v).toLocaleString('en-IN')}` : `${Number(v).toLocaleString('en-IN')}${unit || ''}`);
  const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, fontSize: 13 }, formatter: fmt };

  let chart;
  if (kind === 'pie') {
    const rows = labels.map((name, i) => ({ name, value: series[0].values[i] ?? 0 }));
    chart = (
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="name" outerRadius="80%" isAnimationActive={false}>
          {rows.map((row, i) => <Cell key={row.name} fill={COLORS[i % COLORS.length]} />)}
        </Pie>
        <Tooltip {...tip} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    );
  } else {
    const [Chart, Mark] = BY_KIND[kind] || BY_KIND.line;
    const rows = labels.map((x, i) => Object.fromEntries([['x', x], ...series.map((s) => [s.name, s.values[i]])]));
    chart = (
      <Chart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} minTickGap={16} />
        <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} width={48} tickFormatter={fmt} domain={['auto', 'auto']} />
        <Tooltip {...tip} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Mark key={s.name} type="monotone" dataKey={s.name} stroke={COLORS[i]} fill={COLORS[i]}
            fillOpacity={kind === 'area' ? 0.15 : 1} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
        ))}
      </Chart>
    );
  }

  return (
    <figure className="private rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-3">
      <figcaption className="mb-2 text-[13px] font-semibold text-[var(--text)]">{title}</figcaption>
      <div className="h-52" role="img" aria-label={`${kind} chart: ${title}`}>
        <ResponsiveContainer width="100%" height="100%">{chart}</ResponsiveContainer>
      </div>
    </figure>
  );
};

export default ChatChart;
