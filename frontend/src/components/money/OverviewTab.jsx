import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Card from '../ui/Card';
import ListRow from '../ui/ListRow';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import { inr, pct, tone } from '../ui/format';
import ValueChart from './ValueChart';
import useHoldings from './useHoldings';
import useSymbolNews from '../../hooks/useSymbolNews';
import { ImpactChips } from '../common/NewsImpacts';
import { driverRows, kindLabel, topMovers, whyLine } from '../../utils/money';
import Stat from '../ui/Stat';
import { toneText } from '../ui/tone';
import { stockPath } from '../../utils/stocks';
import { AiCard, AiText, AiState } from '../ai/AiSummary';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';

/** The AI's daily review, folded to its opening lines (the figures above already say most of it). */
const WhyMoved = () => {
  const { data, status, retry } = useStored(endpoints.mine.reviewLatest);
  const [open, setOpen] = useState(false);
  return (
    <AiCard title="Why your money moved" asOf={data?.date}>
      <AiState status={status} retry={retry} message="Could not load your review." />
      {status === 'empty' && <Empty title="No review yet" body="Your first review arrives after today's 16:00 pass." />}
      {status === 'ok' && (
        <>
          <div className={open ? '' : 'max-h-36 overflow-hidden [mask-image:linear-gradient(to_bottom,black_60%,transparent)]'}>
            <AiText text={data.text} collapse={false} />
          </div>
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
            className="mt-1 inline-flex min-h-11 items-center text-[14px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[8px]">
            {open ? 'Show less' : 'Read the full review'}
          </button>
        </>
      )}
    </AiCard>
  );
};

const PERIODS = [['month', 'This month'], ['all', 'All time']];

/** Who made and who cost the money (/mine/overview `drivers`): gainers then losers as bars from a centre line,
 *  on one scale, this month or all time. */
const Drivers = ({ drivers }) => {
  const [period, setPeriod] = useState('month');
  const rows = driverRows(drivers?.[period]);
  if (!drivers) return null;
  return (
    <Card title="What drove it" action={(
      <div role="group" aria-label="Period" className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
        {PERIODS.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={period === id} onClick={() => setPeriod(id)}
            className={`tap min-h-8 rounded-[9px] px-2.5 text-[13px] font-semibold ${period === id ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-muted)]'}`}>{label}</button>
        ))}
      </div>
    )}>
      {rows.length === 0 ? <Empty title="Nothing yet" body="Contributions show once a holding has moved over this period." /> : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={r.symbol}>
              <Link to={stockPath(r.symbol)} className="tap -mx-2 grid min-h-10 grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_5.5rem] items-center gap-3 rounded-[10px] px-2 hover:bg-[var(--surface-2)]">
                <span className="truncate text-[14px] font-medium text-[var(--text)]">{r.symbol}</span>
                <span className="relative h-2 rounded-full bg-[var(--surface-2)]" aria-hidden="true">
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-[var(--border)]" />
                  <span className={`absolute inset-y-0 rounded-full ${r.contribution >= 0 ? 'left-1/2 bg-[var(--gain)]' : 'right-1/2 bg-[var(--loss)]'}`} style={{ width: `${r.share * 50}%` }} />
                </span>
                <span className={`private text-right text-[14px] font-semibold tabular-nums ${toneText(tone(r.contribution))}`}>{inr(r.contribution, { sign: true })}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
};

/** How the money is spread (/mine/overview `mix`): concentration in words, stocks vs ETFs vs funds, then sectors. */
const Mix = ({ mix }) => {
  if (!mix?.count) return null;
  const max = Math.max(1, ...(mix.sectors || []).map((x) => x.pct));
  return (
    <Card title="Your mix">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Largest" value={`${Math.round(mix.top_pct)}%`} delta={mix.top_symbol} />
        <Stat label="Top 5" value={`${Math.round(mix.top5_pct)}%`} delta={`of ${mix.count} holdings`} />
        <Stat label="Spread like" value={Math.round(mix.effective_holdings)} delta="equal holdings" />
      </div>
      {mix.types?.length > 0 && (
        <div className="mt-4">
          <div className="flex h-2.5 overflow-hidden rounded-full" role="img" aria-label={mix.types.map((t) => `${kindLabel(t.kind)} ${Math.round(t.pct)}%`).join(', ')}>
            {mix.types.map((t, i) => <span key={t.kind} style={{ width: `${t.pct}%`, background: `var(--chart-${i + 1})` }} />)}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 text-[12px] text-[var(--text-muted)] tabular-nums">
            {mix.types.map((t, i) => (
              <span key={t.kind} className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{ background: `var(--chart-${i + 1})` }} aria-hidden="true" />{kindLabel(t.kind)} {Math.round(t.pct)}%</span>
            ))}
          </div>
        </div>
      )}
      {mix.sectors?.length > 0 && (
        <ul className="mt-4 space-y-2">
          {mix.sectors.slice(0, 6).map((x) => (
            <li key={x.sector} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3rem] items-center gap-3 text-[13px]">
              <span className="truncate text-[var(--text)]">{x.sector}</span>
              <span className="h-1.5 rounded-full bg-[var(--surface-2)]" aria-hidden="true"><span className="block h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${(x.pct / max) * 100}%` }} /></span>
              <span className="text-right tabular-nums text-[var(--text-muted)]">{Math.round(x.pct)}%</span>
            </li>
          ))}
          <li className="text-[12px] text-[var(--text-muted)]">Sectors of your stocks, as a share of the whole account.</li>
        </ul>
      )}
    </Card>
  );
};

/** Value vs NIFTY, what drove it, the mix, today's three biggest movers with a one-line why, then the AI review.
 *  `headline` and `overview` come from /mine/overview. */
const OverviewTab = ({ headline, overview }) => {
  const { snapshot, loading, error, reload } = useHoldings();
  const movers = useMemo(() => topMovers((snapshot?.holdings || []).filter((h) => h.kind !== 'MF'), 3), [snapshot]);
  const { news } = useSymbolNews(movers.map((m) => m.symbol));

  // No account yet: the headline Empty above already says what to do; do not stack four more empties.
  if (!headline) return null;

  return (
    <div className="space-y-4">
      <ValueChart />
      <Drivers drivers={overview?.drivers} />
      <Mix mix={overview?.mix} />

      <Card title="Biggest movers today" action={<Link to="/money?tab=holdings" className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">All holdings<ChevronRight className="w-4 h-4" aria-hidden="true" /></Link>}>
        {loading ? (
          <Skeleton rows={3} />
        ) : error ? (
          <ErrorLine message="Couldn't load your holdings." onRetry={() => reload()} />
        ) : movers.length === 0 ? (
          <Empty title="No moves to show" body="Movers appear once your holdings have a price today." />
        ) : (
          movers.map((m) => (
            <ListRow
              key={m.symbol}
              to={stockPath(m.symbol)}
              dense
              title={m.symbol}
              sub={whyLine({ ...m, news: news?.[m.symbol] })}
              extra={news?.[m.symbol]?.headline && <ImpactChips impacts={news[m.symbol].impacts} />}
              right={`${inr(m.day_rupees, { sign: true })} · ${pct(m.day_pct, { sign: true })}`}
              rightTone={tone(m.day_rupees)}
            />
          ))
        )}
      </Card>

      <WhyMoved />
    </div>
  );
};

export default OverviewTab;
