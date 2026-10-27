import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import api, { endpoints } from '../../utils/api';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import ListRow from '../ui/ListRow';
import AsOf from '../ui/AsOf';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { divergence, sortSectors } from '../../utils/market';
import { stockPath } from '../../utils/stocks';
import { sectorPath } from '../../utils/routes';
import { heatColor } from '../ui/chartTheme';
import useSection from '../../hooks/useSection';

const SORTS = [
  { id: 'move', label: 'Move' },
  { id: 'news', label: 'News' },
  { id: 'breadth', label: 'Breadth' },
];

const loadScan = () => api.get(endpoints.marketScan).then((r) => r.data);

const Change = ({ value }) => <span className={toneText(tone(value))}>{pct(value / 100, { sign: true })}</span>;

const ExtremeRows = ({ rows, ref52 }) => rows.slice(0, 5).map((m) => (
  <ListRow privateValue={false} key={m.symbol} dense title={m.symbol}
       sub={`${m.sector} · ${pct(m.price / m[ref52] - 1, { sign: true, dp: 1 })} from it`} to={stockPath(m.symbol)}
       right={<><span className="text-[var(--text)]">{Number(m.price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>{'  '}<Change value={m.change_pct} /></>} />
));

const SortControl = ({ value, onChange }) => (
  <div role="group" aria-label="Sort sectors by" className="mb-3 flex items-center gap-2">
    <span className="text-[13px] text-[var(--text-muted)]">Sort</span>
    <div className="flex flex-1 gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
      {SORTS.map((s) => (
        <button key={s.id} type="button" aria-pressed={s.id === value} onClick={() => onChange(s.id)}
          className={`flex-1 min-h-11 rounded-[8px] px-3 text-[14px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
            s.id === value ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
          {s.label}
        </button>
      ))}
    </div>
  </div>
);

const Cell = ({ s, maxAbs }) => {
  const flag = divergence(s);
  return (
    <Link to={sectorPath(s.sector)} className="block min-h-11 rounded-[10px] p-2.5 active:opacity-70 text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]" style={{ background: heatColor(s.change_pct, maxAbs) }}>
      <div className="text-[13px] truncate" title={s.sector}>{s.sector}</div>
      <div className="text-[15px] font-semibold tabular-nums">{pct(s.change_pct / 100, { sign: true })}</div>
      <div className="text-[13px] tabular-nums">{s.up} of {s.n} up</div>
      {s.sentiment != null && (
        <div className="mt-1 flex items-center gap-1 text-[13px] tabular-nums">
          <span aria-hidden="true" className="inline-block size-2 shrink-0 rounded-full" style={{ background: s.sentiment > 0 ? 'var(--gain)' : s.sentiment < 0 ? 'var(--loss)' : 'var(--text-muted)' }} />
          News {s.sentiment > 0 ? '+' : ''}{s.sentiment.toFixed(2)}
        </div>
      )}
      {flag && <div className="mt-1 inline-block rounded-full border border-[var(--text)] px-1.5 text-[13px] font-semibold">{flag}</div>}
    </Link>
  );
};

const Sectors = () => {
  const [{ data, error }, retry] = useSection(loadScan);
  const [by, setBy] = useState('move');
  if (error) return <Card title="Sectors"><ErrorLine message="Could not load the sectors." onRetry={retry} /></Card>;
  if (!data) return <Card title="Sectors"><Skeleton rows={4} /></Card>;
  if (!data.sectors?.length) return <Card title="Sectors"><Empty title="No sector data yet" body="Sectors fill in once the market feed has prices." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} /></Card>;
  const maxAbs = Math.max(1, ...data.sectors.map((s) => Math.abs(s.change_pct)));
  const high = data.near_high || [];
  const low = data.near_low || [];
  return (
    <div className="space-y-3">
      <Card title="Sectors today">
        <SortControl value={by} onChange={setBy} />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {sortSectors(data.sectors, by).map((s) => <Cell key={s.sector} s={s} maxAbs={maxAbs} />)}
        </div>
        <p className="mt-2 text-[13px] text-[var(--text-muted)]">Average move of the Nifty 200 stocks in each sector. Deeper colour, bigger move. News: the sector's headline mood (-1 to +1); flagged when it disagrees with the price.</p>
        <AsOf at={data.at} />
      </Card>
      <Card title="Near 52-week highs and lows">
        <p className="mb-1 text-[13px] text-[var(--text-muted)]">52-week high: the highest price in the past year. Listed here: within 2% of it (or of the low).</p>
        {!high.length && !low.length
          ? <Empty title="Nothing at an extreme" body="No Nifty 200 name is within 2% of its 52-week high or low." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
          : (
            <>
              {high.length > 0 && <h3 className="text-[13px] font-semibold text-[var(--gain)]">Near the high</h3>}
              <ExtremeRows rows={high} ref52="high_52w" />
              {low.length > 0 && <h3 className="mt-3 text-[13px] font-semibold text-[var(--loss)]">Near the low</h3>}
              <ExtremeRows rows={low} ref52="low_52w" />
            </>
          )}
      </Card>
    </div>
  );
};

export default Sectors;
