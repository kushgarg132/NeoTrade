import React, { useCallback, useEffect, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import { Link } from 'react-router-dom';
import Badge from '../ui/Badge';
import AsOf from '../ui/AsOf';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { sectorRows } from '../../utils/market';
import { formatDateTime } from '../../utils/formatters';
import { stockPath } from '../../utils/stocks';
import { X, ChevronRight } from 'lucide-react';
import { heatColor } from '../ui/chartTheme';
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

/** One quote line. Public market data, so no `private` blur (the shared list row blurs its value). */
const Row = ({ title, sub, right, rightTone = 'neutral', to, onClick, dense = false }) => {
  const body = (
    <>
      <div className="min-w-0 flex-1">
        <div className={`${dense ? 'text-[14px]' : 'text-[15px]'} font-medium text-[var(--text)] truncate`}>{title}</div>
        {sub && <div className="text-[12px] text-[var(--text-muted)] truncate">{sub}</div>}
      </div>
      {right != null && <div className={`shrink-0 text-right ${dense ? 'text-[14px]' : 'text-[15px]'} tabular-nums ${toneText(rightTone)}`}>{right}</div>}
      {(to || onClick) && <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
    </>
  );
  const cls = `flex w-full items-center gap-3 ${dense ? 'min-h-11 py-1' : 'min-h-14 py-2'} text-left border-b border-[var(--border)] last:border-b-0 ${to || onClick ? 'active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]' : ''}`;
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  if (onClick) return <button type="button" onClick={onClick} className={cls}>{body}</button>;
  return <div className={cls}>{body}</div>;
};

const EXPLAINABLE = new Set(['^NSEI', '^NSEBANK', '^BSESN']); // the indices the explanation endpoint covers

const Brief = () => {
  const { data, status, retry } = useStored(endpoints.marketBrief);
  const shown = REGIME[data?.regime];
  return (
    <AiCard title="Market today" asOf={data?.as_of}>
      <AiState status={status} retry={retry} message="Could not load the market brief." />
      {status === 'empty' && <Empty title="No brief yet" body="The market brief appears once the news desk has written one." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />}
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
  return (
    <Card title="Indices">
      {error ? <ErrorLine message="Could not load the indices." onRetry={retry} />
        : !data ? <Skeleton rows={4} />
        : !data.length ? <Empty title="No index quotes yet" body="They appear once the market feed is up." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
        : data.map((i) => (
          <Row key={i.name} title={i.name}
                   sub={Number.isFinite(i.change) ? `${i.change > 0 ? '+' : ''}${i.change.toFixed(2)} pts` : null}
                   right={<><span className="text-[var(--text)]">{Number(i.value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>{'  '}{pct(i.percent / 100, { sign: true })}</>}
                   rightTone={tone(i.percent)}
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
        : !data.regime && !events.length ? <Empty title="No read on the market yet" body="The regime and the day's events show here once the ingest worker has them." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
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
    <Card title="Sector news mood">
      {error ? <ErrorLine message="Could not load sector news." onRetry={retry} />
        : !data ? <Skeleton rows={4} />
        : !data.length ? <Empty title="No sector news yet" body="Sectors show up as scored stories name them." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
        : (
          <>
            <p className="mb-1 text-[13px] text-[var(--text-muted)]">From scored headlines, not prices: + is good news for the sector, - is bad.</p>
            {data.map((s) => (
              <Row key={s.sector} dense title={s.sector} sub={`${s.count} ${s.count === 1 ? 'story' : 'stories'}`}
                   right={`${s.score > 0 ? '+' : ''}${s.score}`} rightTone={tone(s.score)} />
            ))}
          </>
        )}
    </Card>
  );
};

const Change = ({ value }) => <span className={toneText(tone(value))}>{pct(value / 100, { sign: true })}</span>;

const MoverRows = ({ rows, sub }) => rows.map((m) => (
  <Row key={m.symbol} dense title={m.symbol} sub={sub ? sub(m) : m.sector} to={stockPath(m.symbol)}
       right={<><span className="text-[var(--text)]">{Number(m.price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>{'  '}<Change value={m.change_pct} /></>} />
));

/** Advancing / declining / flat share of the Nifty 200, as one bar. Counts print beside it. */
const BreadthBar = ({ b }) => {
  const flat = Math.max(0, b.n - b.up - b.down);
  const w = (k) => `${(k / b.n) * 100}%`;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 tabular-nums text-[15px] font-semibold">
        <span className="text-[var(--gain)]">+{b.up} up</span>
        <span className="text-[var(--text-muted)] text-[13px] font-medium">{flat} flat</span>
        <span className="text-[var(--loss)]">-{b.down} down</span>
      </div>
      <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-[var(--heat-0)]" role="img" aria-label={`${b.up} advancing, ${b.down} declining, ${flat} unchanged of ${b.n}`}>
        <div style={{ width: w(b.up), background: 'var(--heat-pos-3)' }} />
        <div style={{ width: w(flat) }} />
        <div style={{ width: w(b.down), background: 'var(--heat-neg-3)' }} />
      </div>
      <p className="mt-2 text-[13px] text-[var(--text-muted)]">Breadth: how many of the Nifty 200 stocks are rising vs falling today. More up than down means the move is broad, not just a few heavyweights.</p>
    </div>
  );
};

/** One GET /market/scan (Nifty 200 from the quote cache, cached 5 min) feeds four cards. */
const Scan = () => {
  const [{ data, error }, retry] = useSection(loadScan);
  if (error) return <Card title="Nifty 200 today"><ErrorLine message="Could not load the market scan." onRetry={retry} /></Card>;
  if (!data) return <Card title="Nifty 200 today"><Skeleton rows={4} /></Card>;
  if (!data.breadth?.n) return <Card title="Nifty 200 today"><Empty title="No quotes yet" body="The scan fills in once the market feed has prices." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} /></Card>;
  const far = (m, ref) => `${m.sector} · ${pct(m.price / ref - 1, { sign: true, dp: 1 })} from it`;
  const maxAbs = Math.max(1, ...data.sectors.map((s) => Math.abs(s.change_pct)));
  return (
    <>
      <Card title="Breadth · Nifty 200"><BreadthBar b={data.breadth} /><AsOf at={data.at} /></Card>
      <Card title="Top movers today">
        <h3 className="text-[13px] font-semibold text-[var(--gain)]">Gainers</h3>
        {data.gainers.length ? <MoverRows rows={data.gainers.slice(0, 5)} /> : <p className="py-2 text-[14px] text-[var(--text-muted)]">No stock is up today.</p>}
        <h3 className="mt-3 text-[13px] font-semibold text-[var(--loss)]">Losers</h3>
        {data.losers.length ? <MoverRows rows={data.losers.slice(0, 5)} /> : <p className="py-2 text-[14px] text-[var(--text-muted)]">No stock is down today.</p>}
      </Card>
      <Card title="Sectors today">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {data.sectors.map((s) => (
            <div key={s.sector} className="rounded-[10px] p-2 text-[var(--text)]" style={{ background: heatColor(s.change_pct, maxAbs) }}>
              <div className="text-[13px] truncate" title={s.sector}>{s.sector}</div>
              <div className="text-[15px] font-semibold tabular-nums">{pct(s.change_pct / 100, { sign: true })}</div>
              <div className="text-[12px] opacity-80">{s.up} of {s.n} up</div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-[var(--text-muted)]">Average move of the Nifty 200 stocks in each sector. Deeper colour, bigger move.</p>
      </Card>
      <Card title="Near 52-week highs and lows">
        <p className="mb-1 text-[13px] text-[var(--text-muted)]">52-week high: the highest price in the past year. Listed here: within 2% of it (or of the low).</p>
        {!data.near_high.length && !data.near_low.length
          ? <Empty title="Nothing at an extreme" body="No Nifty 200 name is within 2% of its 52-week high or low." action={<Button variant="secondary" onClick={retry}>Refresh</Button>} />
          : (
            <>
              {data.near_high.length > 0 && <h3 className="text-[13px] font-semibold text-[var(--gain)]">Near the high</h3>}
              <MoverRows rows={data.near_high.slice(0, 5)} sub={(m) => far(m, m.high_52w)} />
              {data.near_low.length > 0 && <h3 className="mt-3 text-[13px] font-semibold text-[var(--loss)]">Near the low</h3>}
              <MoverRows rows={data.near_low.slice(0, 5)} sub={(m) => far(m, m.low_52w)} />
            </>
          )}
      </Card>
    </>
  );
};

const Pulse = () => (
  <div className="space-y-3">
    <Indices />
    <Scan />
    <Brief />
    <Regime />
    <Sectors />
  </div>
);

export default Pulse;
