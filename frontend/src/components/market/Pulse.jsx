import React, { useCallback, useEffect, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import ListRow from '../ui/ListRow';
import Badge from '../ui/Badge';
import AsOf from '../ui/AsOf';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { sectorRows, breadth } from '../../utils/market';
import { formatDateTime } from '../../utils/formatters';
import { stockPath } from '../../utils/stocks';
import { X } from 'lucide-react';
import { AiCard, AiText, AiState } from '../ai/AiSummary';
import useStored from '../../hooks/useStored';

const REGIME = {
  risk_off: { label: 'Risk off', kind: 'alert' },
  risk_on: { label: 'Risk on', kind: 'proven' },
  neutral: { label: 'Neutral', kind: 'neutral' },
};

/** A section that loads itself: Skeleton, ErrorLine + Retry, then `children(data)`. */
const useSection = (load) => {
  const [state, setState] = useState({ data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    load().then((data) => live && setState({ data, error: null })).catch(() => live && setState({ data: null, error: true }));
    return () => { live = false; };
  }, [load, tick]);
  const retry = useCallback(() => { setState({ data: null, error: null }); setTick((t) => t + 1); }, []);
  return [state, retry];
};

const loadIndices = () => api.get(endpoints.marketIndices).then((r) => r.data);
const loadToday = () => api.get(endpoints.today).then((r) => r.data.backdrop || {});
const loadScan = () => api.get(endpoints.marketScan).then((r) => r.data);
const loadSectors = () => api.get(endpoints.newsFeed, { params: { limit: 50, scope: 'SECTOR' } }).then((r) => sectorRows(r.data.items));

const EXPLAINABLE = new Set(['^NSEI', '^NSEBANK', '^BSESN']); // the indices the explanation endpoint covers

const Brief = () => {
  const { data, status, retry } = useStored(endpoints.marketBrief);
  const shown = REGIME[data?.regime];
  return (
    <AiCard title="Market today" asOf={data?.as_of}>
      <AiState status={status} retry={retry} message="Could not load the market brief." />
      {status === 'empty' && <Empty title="No brief yet" body="The market brief appears once the news desk has written one." />}
      {status === 'ok' && (
        <div className="space-y-2">
          {shown && <Badge kind={shown.kind}>{shown.label}</Badge>}
          <AiText text={data.text} />
        </div>
      )}
    </AiCard>
  );
};

/** Why an index moved: the existing explanation endpoint, called on tap. 503 means the model is off. */
const IndexSheet = ({ index, onClose }) => {
  const { data, status, code, retry } = useStored(endpoints.marketIndexAnalysis(index.symbol));
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40" onClick={onClose}>
      <div role="dialog" aria-label={`Why ${index.name} moved`} className="bg-[var(--bg)] w-full sm:max-w-xl max-h-[90vh] overflow-y-auto p-3 sm:p-4 rounded-t-[16px] sm:rounded-[16px]" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-end">
          <button type="button" onClick={onClose} aria-label="Close" className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]"><X className="w-5 h-5" /></button>
        </div>
        <AiCard title={`Why ${index.name} moved`} asOf={data?.session?.date}>
          {status === 'loading' && <Skeleton rows={4} />}
          {status === 'error' && code === 503 && <ErrorLine message="Explanation unavailable right now" onRetry={retry} />}
          {status === 'error' && code !== 503 && <ErrorLine message="Could not load the explanation." onRetry={retry} />}
          {status === 'ok' && (
            <>
              <AiText text={data.analysis} />
              {data.headlines?.length > 0 && (
                <ul className="mt-3 list-disc pl-5 text-[13px] text-[var(--text-muted)]">
                  {data.headlines.slice(0, 3).map((h) => <li key={h.title}>{h.title}</li>)}
                </ul>
              )}
            </>
          )}
        </AiCard>
      </div>
    </div>
  );
};

const Indices = () => {
  const [open, setOpen] = useState(null);
  const [{ data, error }, retry] = useSection(loadIndices);
  const b = breadth(data || []);
  return (
    <Card title="Indices" action={data?.length ? <Badge kind="neutral">{b.up} up · {b.down} down</Badge> : null}>
      {error ? <ErrorLine message="Could not load the indices." onRetry={retry} />
        : !data ? <Skeleton rows={4} />
        : !data.length ? <Empty title="No index quotes yet" body="They appear once the market feed is up." />
        : data.map((i) => (
          <ListRow key={i.name} title={i.name} chevron={false}
                   sub={Number.isFinite(i.change) ? `${i.change > 0 ? '+' : ''}${i.change.toFixed(2)}` : null}
                   right={`${Number(i.value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}  ${pct(i.percent / 100, { sign: true })}`}
                   rightTone={tone(i.percent)}
                   chevron={EXPLAINABLE.has(i.symbol)}
                   onClick={EXPLAINABLE.has(i.symbol) ? () => setOpen(i) : undefined} />
        ))}
      {data?.length > 0 && <AsOf rows={data} />}
      {open && <IndexSheet index={open} onClose={() => setOpen(null)} />}
    </Card>
  );
};

const Regime = () => {
  const [{ data, error }, retry] = useSection(loadToday);
  const shown = REGIME[data?.regime?.label];
  const events = data?.events || [];
  return (
    <Card title="Regime and events">
      {error ? <ErrorLine message="Could not load the market backdrop." onRetry={retry} />
        : !data ? <Skeleton rows={3} />
        : !data.regime && !events.length ? <Empty title="No read on the market yet" body="The regime and the day's events show here once the ingest worker has them." />
        : (
          <div className="space-y-3">
            {data.regime && (
              <div className="flex flex-wrap gap-1.5">
                {shown && <Badge kind={shown.kind}>{shown.label}</Badge>}
                {(data.regime.drivers || []).map((d) => <Badge key={d}>{d}</Badge>)}
              </div>
            )}
            {events.slice(0, 5).map((e) => (
              <div key={`${e.at}-${e.title}`} className="text-[14px]">
                <div className="text-[var(--text)]">{e.country} {e.title}</div>
                <div className="text-[13px] text-[var(--text-muted)]">
                  {formatDateTime(e.at)}{e.forecast ? ` · forecast ${e.forecast}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
    </Card>
  );
};

const Sectors = () => {
  const [{ data, error }, retry] = useSection(loadSectors);
  return (
    <Card title="Sectors in the news">
      {error ? <ErrorLine message="Could not load sector news." onRetry={retry} />
        : !data ? <Skeleton rows={4} />
        : !data.length ? <Empty title="No sector news yet" body="Sectors show up as scored stories name them." />
        : data.map((s) => (
          <ListRow key={s.sector} title={s.sector} chevron={false}
                   sub={`${s.count} ${s.count === 1 ? 'story' : 'stories'}`}
                   right={`${s.score > 0 ? '+' : ''}${s.score}`} rightTone={tone(s.score)} />
        ))}
    </Card>
  );
};

const Change = ({ value }) => <span className={toneText(tone(value))}>{pct(value / 100, { sign: true })}</span>;

const MoverRows = ({ rows, sub }) => rows.map((m) => (
  <ListRow key={m.symbol} title={m.symbol} sub={sub ? sub(m) : m.sector} to={stockPath(m.symbol)} right={<Change value={m.change_pct} />} />
));

/** One GET /market/scan (Nifty 200 from the quote cache, cached 5 min) feeds three cards. */
const Scan = () => {
  const [{ data, error }, retry] = useSection(loadScan);
  const [side, setSide] = useState('gainers');
  if (error) return <Card title="Nifty 200 today"><ErrorLine message="Could not load the market scan." onRetry={retry} /></Card>;
  if (!data) return <Card title="Nifty 200 today"><Skeleton rows={4} /></Card>;
  if (!data.breadth?.n) return <Card title="Nifty 200 today"><Empty title="No quotes yet" body="The scan fills in once the market feed has prices." /></Card>;
  const far = (m, ref) => `${m.sector} · ${pct(m.price / ref - 1, { sign: true, dp: 1 })} from it`;
  return (
    <>
      <Card title="Biggest movers · Nifty 200" action={<Badge kind="neutral">{data.breadth.up} up · {data.breadth.down} down</Badge>}>
        <div className="flex gap-2 mb-2" role="tablist">
          {[['gainers', 'Gainers'], ['losers', 'Losers']].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={side === id} onClick={() => setSide(id)}
                    className={`min-h-11 px-3 rounded-[10px] text-[14px] font-semibold ${side === id ? 'bg-[var(--surface-2)] text-[var(--text)]' : 'text-[var(--text-muted)]'}`}>
              {label}
            </button>
          ))}
        </div>
        <MoverRows rows={data[side].slice(0, 5)} />
        <AsOf at={data.at} />
      </Card>
      <Card title="Sectors today">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {data.sectors.map((s) => (
            <div key={s.sector} className={`rounded-[10px] p-2 ${s.change_pct > 0 ? 'bg-[var(--gain-wash)]' : s.change_pct < 0 ? 'bg-[var(--loss-wash)]' : 'bg-[var(--surface-2)]'}`}>
              <div className="text-[13px] text-[var(--text)] truncate" title={s.sector}>{s.sector}</div>
              <div className="text-[14px] font-semibold tabular-nums"><Change value={s.change_pct} /></div>
              <div className="text-[12px] text-[var(--text-muted)]">{s.up} of {s.n} up</div>
            </div>
          ))}
        </div>
      </Card>
      <Card title="Near 52-week highs and lows">
        {!data.near_high.length && !data.near_low.length
          ? <p className="text-[14px] text-[var(--text-muted)]">No Nifty 200 name is within 2% of its 52-week high or low.</p>
          : (
            <>
              {data.near_high.length > 0 && <h3 className="text-[13px] font-semibold text-[var(--text-muted)]">Near the high</h3>}
              <MoverRows rows={data.near_high.slice(0, 5)} sub={(m) => far(m, m.high_52w)} />
              {data.near_low.length > 0 && <h3 className="mt-3 text-[13px] font-semibold text-[var(--text-muted)]">Near the low</h3>}
              <MoverRows rows={data.near_low.slice(0, 5)} sub={(m) => far(m, m.low_52w)} />
            </>
          )}
      </Card>
    </>
  );
};

const Pulse = () => (
  <div className="space-y-3">
    <Brief />
    <Indices />
    <Regime />
    <Sectors />
    <Scan />
  </div>
);

export default Pulse;
