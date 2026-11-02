import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import api, { endpoints } from '../../utils/api';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import AsOf from '../ui/AsOf';
import Badge from '../ui/Badge';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { breadthWord, divergence, filterSectors, isClosed, newsMood, sortSectors } from '../../utils/market';
import ChipRow from '../ui/ChipRow';
import { stockPath } from '../../utils/stocks';
import { sectorPath } from '../../utils/routes';
import useSection from '../../hooks/useSection';

const SORTS = [
  { id: 'move', label: 'Move' },
  { id: 'news', label: 'News' },
  { id: 'breadth', label: 'Breadth' },
];

const SHOWS = [
  { id: 'all', label: 'All' },
  { id: 'up', label: 'Rising' },
  { id: 'down', label: 'Falling' },
  { id: 'flagged', label: 'Flagged' },
];
const EXTREMES = [
  { id: 'both', label: 'Both' },
  { id: 'high', label: 'Highs' },
  { id: 'low', label: 'Lows' },
];

/** A filter that left nothing: say so, one tap back to everything. */
const NoMatch = ({ onClear }) => (
  <p className="py-4 text-[14px] text-[var(--text-muted)]">
    Nothing matches.{' '}
    <button type="button" onClick={onClear} className="min-h-11 font-medium text-[var(--accent)] underline">Clear</button>
  </p>
);

const loadScan = () => api.get(endpoints.marketScan).then((r) => r.data);

const Panel = ({ children, className = '' }) => (
  <section className={`rounded-[20px] border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}>{children}</section>
);

/** Up vs down among the Nifty 200 as one split bar, with its plain word ("Broad rally"). */
const Breadth = ({ b }) => {
  const flat = b.n - b.up - b.down;
  return (
    <Panel>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">{breadthWord(b) || 'Breadth'}</h2>
        <span className="text-[13px] text-[var(--text-muted)]">Nifty 200 · {isClosed() ? 'last session' : 'today'}</span>
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-[var(--surface-2)]" role="img"
        aria-label={`${b.up} stocks rising, ${b.down} falling, ${flat} flat, of ${b.n}`}>
        <div className="bg-[var(--gain)]" style={{ width: `${(b.up / b.n) * 100}%` }} />
        <div className="ml-auto bg-[var(--loss)]" style={{ width: `${(b.down / b.n) * 100}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-[13px] tabular-nums">
        <span className="text-[var(--gain)] font-semibold">▲ {b.up} rising</span>
        {flat > 0 && <span className="text-[var(--text-muted)]">{flat} flat</span>}
        <span className="text-[var(--loss)] font-semibold">▼ {b.down} falling</span>
      </div>
    </Panel>
  );
};

const SortControl = ({ value, onChange }) => (
  <div role="group" aria-label="Sort sectors by" className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
    {SORTS.map((s) => (
      <button key={s.id} type="button" aria-pressed={s.id === value} onClick={() => onChange(s.id)}
        className={`tap min-h-9 rounded-[9px] px-3 text-[13px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
          s.id === value ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}>
        {s.label}
      </button>
    ))}
  </div>
);

/** A bar growing right (gain) or left (loss) from the zero line in the middle, scaled to the day's biggest move. */
const MoveBar = ({ value, maxAbs }) => {
  const w = `${Math.min(50, (Math.abs(value) / maxAbs) * 50)}%`;
  return (
    <div className="relative h-1.5 rounded-full bg-[var(--surface-2)]" aria-hidden="true">
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-[var(--border)]" />
      {value !== 0 && (
        <div className={`absolute inset-y-0 rounded-full ${value > 0 ? 'left-1/2 bg-[var(--gain)]' : 'right-1/2 bg-[var(--loss)]'}`} style={{ width: w }} />
      )}
    </div>
  );
};

// The NSE industry names, as traders say them, where the full name does not fit a phone row (full name on sm+).
const SHORT = {
  'Fast Moving Consumer Goods': 'FMCG', 'Automobile and Auto Components': 'Auto', 'Oil Gas & Consumable Fuels': 'Oil & Gas',
  'Information Technology': 'IT', 'Telecommunication': 'Telecom', 'Financial Services': 'Financials',
  'Construction Materials': 'Building materials', 'Consumer Durables': 'Durables',
};

/** One sector on one line: name, the bar from zero, the signed move, how many of its stocks rose. */
const Row = ({ s, maxAbs, by }) => {
  const flag = divergence(s);
  const mood = newsMood(s.sentiment);
  const short = SHORT[s.sector];
  return (
    <li>
      <Link to={sectorPath(s.sector)} title={s.sector}
        className="tap -mx-2 grid min-h-11 grid-cols-[minmax(0,1fr)_minmax(48px,20%)_52px_36px] sm:grid-cols-[220px_minmax(0,1fr)_64px_56px] items-center gap-x-2.5 sm:gap-x-3 rounded-[12px] px-2 py-1.5 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        <span className="min-w-0 truncate text-[14px] sm:text-[15px] font-medium text-[var(--text)]">
          {short ? <><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{s.sector}</span></> : s.sector}
        </span>
        <MoveBar value={s.change_pct} maxAbs={maxAbs} />
        <span className={`text-right text-[15px] font-semibold tabular-nums ${toneText(tone(s.change_pct))}`}>{pct(s.change_pct / 100, { sign: true })}</span>
        <span className="text-right text-[12px] tabular-nums text-[var(--text-muted)]" aria-label={`${s.up} of ${s.n} stocks up`}>{s.up}/{s.n}</span>
        {(flag || (by === 'news' && mood)) && (
          <span className="col-span-4 -mt-0.5 mb-0.5 flex flex-wrap gap-1.5">
            {by === 'news' && mood && <Badge kind={mood.kind}>{mood.label} {s.sentiment > 0 ? '+' : ''}{s.sentiment.toFixed(2)}</Badge>}
            {flag && <Badge kind="unproven">{flag}</Badge>}
          </span>
        )}
      </Link>
    </li>
  );
};

/** A stock within 2% of its 52-week high or low: how far from it, its price and day move. */
const Extreme = ({ m, high }) => {
  const ref = high ? m.high_52w : m.low_52w;
  const gap = Math.abs(m.price / ref - 1);
  return (
    <li>
      <Link to={stockPath(m.symbol)}
        className="tap flex items-center gap-3 rounded-[12px] px-2 py-2.5 -mx-2 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        <span className={`inline-flex w-8 h-8 shrink-0 items-center justify-center rounded-full text-[13px] ${high ? 'bg-[var(--gain-soft)] text-[var(--gain)]' : 'bg-[var(--loss-soft)] text-[var(--loss)]'}`} aria-hidden="true">{high ? '▲' : '▼'}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold text-[var(--text)]">{m.symbol}</div>
          <div className="text-[13px] text-[var(--text-muted)] truncate">
            {gap < 0.0005 ? `At its 52-week ${high ? 'high' : 'low'}` : `${pct(gap, { dp: 1 })} ${high ? 'under' : 'above'} its 52-week ${high ? 'high' : 'low'}`} · {m.sector}
          </div>
        </div>
        <div className="shrink-0 text-right tabular-nums">
          <div className="text-[15px] text-[var(--text)]">{Number(m.price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
          <div className={`text-[12px] ${toneText(tone(m.change_pct))}`}>{pct(m.change_pct / 100, { sign: true })}</div>
        </div>
      </Link>
    </li>
  );
};

const Sectors = () => {
  const [{ data, error }, retry] = useSection(loadScan);
  const [by, setBy] = useState('move');
  const [show, setShow] = useState('all');
  const [ext, setExt] = useState('both');
  if (error) return <Panel><ErrorLine message="Could not load the sectors." onRetry={retry} /></Panel>;
  if (!data) return <Panel><Skeleton rows={6} /></Panel>;
  if (!data.sectors?.length) return <Panel><Empty title="No sector data yet" body="Sectors fill in once the market feed has prices." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} /></Panel>;
  const maxAbs = Math.max(0.5, ...data.sectors.map((s) => Math.abs(s.change_pct)));
  const high = ext === 'low' ? [] : (data.near_high || []).slice(0, 5);
  const low = ext === 'high' ? [] : (data.near_low || []).slice(0, 5);
  const rows = sortSectors(filterSectors(data.sectors, show), by);
  return (
    <div className="space-y-4">
      {data.breadth?.n > 0 && <Breadth b={data.breadth} />}

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">{isClosed() ? 'Sectors · last session' : 'Sectors today'}</h2>
          <SortControl value={by} onChange={setBy} />
        </div>
        <ChipRow label="Show sectors" options={SHOWS} value={show} onChange={setShow} className="mt-2" />
        <div className="mt-3 -mx-0 grid grid-cols-[minmax(0,1fr)_minmax(48px,20%)_52px_36px] sm:grid-cols-[220px_minmax(0,1fr)_64px_56px] gap-x-2.5 sm:gap-x-3 pb-1 text-[12px] text-[var(--text-muted)]" aria-hidden="true">
          <span>Sector</span><span className="text-center">Day move</span><span className="text-right">Avg</span><span className="text-right">Up</span>
        </div>
        {rows.length ? <ul>{rows.map((s) => <Row key={s.sector} s={s} maxAbs={maxAbs} by={by} />)}</ul>
          : <NoMatch onClear={() => setShow('all')} />}
        <p className="mt-2 text-[12px] leading-snug text-[var(--text-muted)]">
          Avg: the average day move of the sector's Nifty 200 stocks; bars share one scale. Up: how many of them rose. A flag means the sector's news mood points the other way.
        </p>
        <AsOf at={data.at} />
      </Panel>

      <Panel>
        <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">Near 52-week highs and lows</h2>
        <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">Within 2% of the highest price in the past year, or of the lowest.</p>
        <ChipRow label="Show highs or lows" options={EXTREMES} value={ext} onChange={setExt} className="mt-2" />
        {!high.length && !low.length && ext !== 'both'
          ? <NoMatch onClear={() => setExt('both')} />
          : !high.length && !low.length
          ? <Empty title="Nothing at an extreme" body="No Nifty 200 name is within 2% of its 52-week high or low." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
          : <ul className="mt-2">{high.map((m) => <Extreme key={m.symbol} m={m} high />)}{low.map((m) => <Extreme key={m.symbol} m={m} />)}</ul>}
      </Panel>
    </div>
  );
};

export default Sectors;
