import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts';
import api, { endpoints } from '../../utils/api';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import Badge from '../ui/Badge';
import ListRow from '../ui/ListRow';
import AsOf from '../ui/AsOf';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { AiMarkdown } from '../ai/AiSummary';
import useStored from '../../hooks/useStored';
import useSection from '../../hooks/useSection';
import { breadthWord } from '../../utils/market';
import { formatDateTime, marketPhase } from '../../utils/formatters';
import { stockPath } from '../../utils/stocks';
import { indexPath } from '../../utils/routes';

const REGIME = {
  risk_off: { label: 'Risk off', kind: 'alert' },
  risk_on: { label: 'Risk on', kind: 'proven' },
  neutral: { label: 'Neutral', kind: 'neutral' },
};
const TILES = ['^NSEI', '^NSEBANK', '^BSESN'];

const loadIndices = () => api.get(endpoints.marketIndices).then((r) => r.data);
const loadToday = () => api.get(endpoints.today).then((r) => r.data.backdrop || {});
const loadScan = () => api.get(endpoints.marketScan).then((r) => r.data);
const num = (v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const refresh = (retry) => <Button variant="secondary" onClick={retry}>Refresh</Button>;
const closed = () => marketPhase() === 'closed';

const Story = () => {
  const { data, status, retry } = useStored(endpoints.marketBrief);
  const [open, setOpen] = useState(false);
  const shown = REGIME[data?.regime];
  return (
    <Card title={closed() ? 'Market · last session' : 'Market today'} action={<span className="text-[13px] text-[var(--text-muted)]">AI summary</span>}>
      {status === 'loading' ? <Skeleton rows={3} />
        : status === 'error' ? <ErrorLine message="Could not load the market brief." onRetry={retry} />
        : status === 'empty' ? <Empty title="No brief yet" body="The market brief appears once the news desk has written one." action={refresh(retry)} />
        : (
          <div className="space-y-2">
            {shown && <Badge kind={shown.kind}>{shown.label}</Badge>}
            <div className={open ? '' : 'line-clamp-2'}><AiMarkdown text={data.text} collapse={false} /></div>
            {data.text.length > 140 && (
              <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
                className="min-h-11 rounded-[8px] text-[14px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
                {open ? 'Show less' : 'Read more'}
              </button>
            )}
            <AsOf at={data.as_of ? Date.parse(data.as_of) : null} />
          </div>
        )}
    </Card>
  );
};

/** Intraday sparkline; renders nothing without 2+ points so the tile stays fine without it. */
const Spark = ({ ticker, up }) => {
  const [points, setPoints] = useState([]);
  useEffect(() => {
    let live = true;
    api.get(endpoints.marketIndexIntraday(ticker)).then((r) => live && setPoints(r.data || [])).catch(() => live && setPoints([]));
    return () => { live = false; };
  }, [ticker]);
  if (points.length < 2) return null;
  return (
    <div className="mt-1 h-8" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Line type="monotone" dataKey="close" dot={false} isAnimationActive={false} strokeWidth={1.5} stroke={up ? 'var(--gain)' : 'var(--loss)'} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

const IndexTile = ({ i }) => (
  <Link to={indexPath(i.symbol)} className="block min-h-[88px] rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-3 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
    <div className="truncate text-[13px] font-medium text-[var(--text-muted)]">{i.name}</div>
    <div className="mt-1 text-[17px] font-bold tabular-nums text-[var(--text)]">{num(i.value)}</div>
    <div className={`text-[13px] font-semibold tabular-nums ${toneText(tone(i.percent))}`}>{pct(i.percent / 100, { sign: true })}</div>
    <Spark ticker={i.symbol} up={!(i.percent < 0)} />
  </Link>
);

const Indices = () => {
  const [{ data, error }, retry] = useSection(loadIndices);
  const tiles = (data || []).filter((i) => TILES.includes(i.symbol));
  const more = (data || []).filter((i) => !TILES.includes(i.symbol));
  return (
    <Card title="Indices">
      {error ? <ErrorLine message="Could not load the indices." onRetry={retry} />
        : !data ? <Skeleton rows={4} />
        : !data.length ? <Empty title="No index quotes yet" body="They appear once the market feed is up." action={refresh(retry)} />
        : (
          <>
            <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-3">{tiles.map((i) => <IndexTile key={i.symbol} i={i} />)}</div>
            {more.length > 0 && (
              <details className="mt-2">
                <summary className="flex min-h-11 cursor-pointer items-center rounded-[8px] text-[14px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">More indices</summary>
                {more.map((i) => (
                  <ListRow privateValue={false} key={i.symbol} dense title={i.name} to={indexPath(i.symbol)}
                    right={<><span className="text-[var(--text)]">{num(i.value)}</span>{'  '}{pct(i.percent / 100, { sign: true })}</>} rightTone={tone(i.percent)} />
                ))}
              </details>
            )}
            <AsOf rows={data} />
          </>
        )}
    </Card>
  );
};

/** Advancing / declining / flat share of the Nifty 200, as one bar. Counts print beside it. */
const BreadthBar = ({ b }) => {
  const flat = Math.max(0, b.n - b.up - b.down);
  const w = (k) => `${(k / b.n) * 100}%`;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 tabular-nums text-[15px] font-semibold">
        <span className="text-[var(--gain)]">+{b.up} up</span>
        <span className="text-[13px] font-medium text-[var(--text-muted)]">{flat} flat</span>
        <span className="text-[var(--loss)]">-{b.down} down</span>
      </div>
      <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-[var(--heat-0)]" role="img" aria-label={`${b.up} advancing, ${b.down} declining, ${flat} unchanged of ${b.n}`}>
        <div style={{ width: w(b.up), background: 'var(--heat-pos-3)' }} />
        <div style={{ width: w(flat) }} />
        <div style={{ width: w(b.down), background: 'var(--heat-neg-3)' }} />
      </div>
    </div>
  );
};

const MoverRows = ({ rows }) => rows.map((m) => (
  <ListRow privateValue={false} key={m.symbol} dense to={stockPath(m.symbol)}
    title={<span className="inline-flex items-center gap-1.5">{m.symbol}{m.news && <span role="img" aria-label="Has news today" className="inline-block size-2 shrink-0 rounded-full bg-[var(--accent)]" />}</span>}
    sub={m.sector}
    right={<><span className="text-[var(--text)]">{num(m.price)}</span>{'  '}<span className={toneText(tone(m.change_pct))}>{pct(m.change_pct / 100, { sign: true })}</span></>} />
));

const MoverList = ({ rows, none }) => (rows.length ? <MoverRows rows={rows.slice(0, 5)} /> : <p className="py-2 text-[14px] text-[var(--text-muted)]">{none}</p>);

/** One GET /market/scan feeds Breadth and Movers. */
const Scan = () => {
  const [{ data, error }, retry] = useSection(loadScan);
  const [side, setSide] = useState('gainers');
  const wrap = (title, body) => <Card title={title}>{body}</Card>;
  const bTitle = closed() ? 'Breadth · Nifty 200 · last session' : 'Breadth · Nifty 200';
  const mTitle = closed() ? 'Movers · last session' : 'Movers today';
  if (error) return (<>{wrap(bTitle, <ErrorLine message="Could not load the market breadth." onRetry={retry} />)}{wrap(mTitle, <ErrorLine message="Could not load the movers." onRetry={retry} />)}</>);
  if (!data) return (<>{wrap(bTitle, <Skeleton rows={3} />)}{wrap(mTitle, <Skeleton rows={4} />)}</>);
  if (!data.breadth?.n) return (<>{wrap(bTitle, <Empty title="No quotes yet" body="Breadth fills in once the market feed has prices." action={refresh(retry)} />)}{wrap(mTitle, <Empty title="No movers yet" body="Movers fill in once the market feed has prices." action={refresh(retry)} />)}</>);
  const word = breadthWord(data.breadth);
  return (
    <>
      <Card title={bTitle}>
        {word && <p className="mb-2 text-[17px] font-bold text-[var(--text)]">{word}</p>}
        <BreadthBar b={data.breadth} />
        <AsOf at={data.at} />
      </Card>
      <Card title={mTitle}>
        <div role="tablist" aria-label="Movers" className="mb-2 flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1 sm:hidden">
          {[['gainers', 'Gainers'], ['losers', 'Losers']].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={side === id} onClick={() => setSide(id)}
              className={`min-h-11 flex-1 rounded-[8px] text-[14px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${side === id ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm' : 'text-[var(--text-muted)]'}`}>{label}</button>
          ))}
        </div>
        <div className="sm:grid sm:grid-cols-2 sm:gap-4">
          <div className={side === 'gainers' ? '' : 'hidden sm:block'}>
            <h3 className="hidden text-[13px] font-semibold text-[var(--gain)] sm:block">Gainers</h3>
            <MoverList rows={data.gainers || []} none="No stock is up today." />
          </div>
          <div className={side === 'losers' ? '' : 'hidden sm:block'}>
            <h3 className="hidden text-[13px] font-semibold text-[var(--loss)] sm:block">Losers</h3>
            <MoverList rows={data.losers || []} none="No stock is down today." />
          </div>
        </div>
      </Card>
    </>
  );
};

const Events = () => {
  const [{ data, error }, retry] = useSection(loadToday);
  const events = (data?.events || []).slice(0, 5);
  if (data && !events.length) return null; // hidden when empty
  return (
    <Card title="Events today">
      {error ? <ErrorLine message="Could not load today's events." onRetry={retry} />
        : !data ? <Skeleton rows={3} />
        : events.map((e) => (
          <div key={`${e.at}-${e.title}`} className="py-1.5 text-[14px]">
            <div className="text-[var(--text)]">{e.country} {e.title}</div>
            <div className="text-[13px] text-[var(--text-muted)]">{formatDateTime(e.at)}{e.forecast ? ` · forecast ${e.forecast}` : ''}</div>
          </div>
        ))}
    </Card>
  );
};

const Today = () => (
  <div className="space-y-3">
    <Story />
    <Indices />
    <Scan />
    <Events />
  </div>
);

export default Today;
