import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, ChevronDown, Minus, X } from 'lucide-react';
import SettingsPage from './SettingsPage';
import Scorecard from '../components/paper/Scorecard';
import TradeLedger from '../components/dashboard/TradeLedger';
import LearningSheet from '../components/journal/LearningSheet';
import MyStrategies from '../components/strategies/MyStrategies';
import Card from '../components/ui/Card';
import Tabs from '../components/ui/Tabs';
import Skeleton from '../components/ui/Skeleton';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import api, { endpoints, getPreferences } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { builtLine, recordLine, statusOf, strategyName } from '../utils/library';
import { gateMeter, readiness } from '../utils/promotion';
import ForwardBadge from '../components/ForwardBadge';
import RotationScorecard from '../components/ai/RotationScorecard';
import { cn } from '../utils/cn';

/**
 * Lab → Strategies. The autopilot trades only the weekly rotation (its record leads); every strategy
 * below is research on paper: status filters, a live-gate meter per strategy, then one tab strip for
 * the track record, your own builds, rejected drafts, every paper trade and what the engine learned.
 */

const STATUS = {
  'live-ready': { label: 'Passes the live gate', kind: 'proven' },
  paper: { label: 'Paper only', kind: 'paper' },
  untested: { label: 'Not backtested', kind: 'neutral' },
  paused: { label: 'Paused by learning', kind: 'alert' },
};
const FILTERS = [['', 'All'], ['live-ready', 'Ready'], ['paper', 'Paper'], ['untested', 'Not backtested'], ['paused', 'Paused']];
const RESEARCH = [
  { id: 'record', label: 'Track record' }, { id: 'mine', label: 'Mine' }, { id: 'rejected', label: 'Rejected' },
  { id: 'trades', label: 'Trades' }, { id: 'learned', label: 'Learned' },
];
const MARK = { pass: [Check, 'text-[var(--gain)]', 'Backtest passed'], fail: [X, 'text-[var(--loss)]', 'Backtest failed'], none: [Minus, 'text-[var(--text-muted)]', 'No backtest'] };

/** The live gate at a glance: backtest mark, then paper days and trades against what promotion needs. */
const GateMeter = ({ row }) => {
  const m = gateMeter(row);
  if (!m) return null; // the status badge and record line already say so
  const [Icon, tone, label] = MARK[m.backtest];
  return (
    <span className="block space-y-1.5 text-[12px] text-[var(--text-muted)]">
      <span className={cn('inline-flex items-center gap-1 font-medium', tone)}><Icon className="w-3.5 h-3.5" aria-hidden="true" />{label}</span>
      {m.bars.length > 0 && (
        <span className="grid grid-cols-2 gap-3">
          {m.bars.map((b) => (
            <span key={b.rule} className="block min-w-0 space-y-1">
              <span className="flex justify-between gap-2 tabular-nums"><span>Paper {b.rule}</span><span>{b.have}/{b.need}</span></span>
              <span className="block h-1.5 rounded-full bg-[var(--surface-2)]" role="progressbar" aria-label={`Paper ${b.rule}`}
                    aria-valuenow={b.have} aria-valuemin={0} aria-valuemax={b.need}>
                <span className={cn('block h-1.5 rounded-full', b.pct >= 1 ? 'bg-[var(--gain)]' : 'bg-[var(--accent)]')} style={{ width: `${b.pct * 100}%` }} />
              </span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
};

const netTone = (card) => {
  const net = card?.stats?.all?.net;
  return net > 0 ? 'text-[var(--gain)]' : net < 0 ? 'text-[var(--loss)]' : 'text-[var(--text-muted)]';
};

/** The page's one timeframe filter (strategies, record and trades), kept in ?book= so old Engine links land here. */
const BOOKS = [
  { key: 'all', label: 'All', mode: undefined },
  { key: 'intraday', label: 'Intraday', mode: 'INTRADAY' },
  { key: 'longterm', label: 'Long term', mode: 'LONGTERM' },
];

const StrategyItem = ({ card, gate, row, gateKnown, open, onToggle, yours }) => {
  const status = STATUS[statusOf(card)];
  return (
    <li className={cn('rounded-[14px] border border-[var(--border)] bg-[var(--surface)] p-3', open && 'ring-1 ring-[var(--accent)]')}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left min-h-11 space-y-1.5">
        <span className="flex items-start gap-2">
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold text-[var(--text)]">{strategyName(card.built ? card.name.replace(/^built:/, '') : card.name)}</span>
            <Badge kind={status.kind}>{status.label}</Badge>
            <ForwardBadge source="engine" name={card.name} />
          </span>
          <ChevronDown className={cn('mt-1 w-4 h-4 shrink-0 text-[var(--text-muted)] transition-transform', open && 'rotate-180')} aria-hidden="true" />
        </span>
        <span className={cn('block text-[13px] tabular-nums', netTone(card))}>{recordLine(card)}</span>
        {gateKnown && <GateMeter row={row} />}
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 border-t border-[var(--border)] pt-2 fade-in">
          {card.built && (
            <>
              <p className="flex flex-wrap gap-2">
                <Badge kind="neutral">{yours ? 'Built · Yours' : 'Built'}</Badge>
                <Badge kind="neutral">{card.built.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>
              </p>
              <p className="text-sm">{card.built.description} — {card.built.thesis}</p>
              <p className="text-[13px] text-[var(--text-muted)]">{builtLine(card.built.metrics, card.built.horizon)}</p>
            </>
          )}
          <p className="text-sm">{gate}</p>
          <p className="text-sm">{card.card?.best_when}</p>
          <p className="text-[13px] text-[var(--text-muted)]">Avoid: {card.card?.avoid_when}</p>
          <p className="text-[13px] text-[var(--text-muted)]">
            {card.card?.style} · suits {(card.card?.regimes ?? []).join(', ').replace(/_/g, '-')}
            {card.card?.needs?.length > 0 && ` · needs ${card.card.needs.join(', ').replace(/_/g, ' ')}`}
          </p>
        </div>
      )}
    </li>
  );
};

/** The weekly builder's (not the user's own, those are in Mine) drafts that failed a check, so a rejected idea is never re-proposed unseen. */
const Rejected = ({ rows }) => {
  if (!rows?.length) return <Empty title="Nothing rejected" body="Ideas the weekly builder drops after a failed check show here." />;
  return (
    <Card>
      <ul className="divide-y divide-[var(--border)]">
        <li className="pb-2.5 text-[13px] text-[var(--text-muted)]">Ideas the weekly builder dropped after a failed check.</li>
        {rows.map((r) => (
          <li key={r.slug} className="py-2.5">
            <Badge kind="neutral">{r.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>
            <span className="block text-sm">{[r.description, r.thesis].filter(Boolean).join(' — ') || r.verdict}</span>
            <span className="block text-[13px] text-[var(--text-muted)]">{builtLine(r.metrics, r.horizon)}</span>
            <span className="block text-[13px] text-[var(--text-muted)]">{r.verdict}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
};

const Strategies = () => {
  const [params, setParams] = useSearchParams();
  const book = BOOKS.find((b) => b.key === params.get('book')) || BOOKS[0];
  const mode = book.mode; // undefined = every timeframe
  const pickBook = (key) => setParams(key === 'all' ? {} : { book: key }, { replace: true });
  // Keyed by mode, so switching shows the skeleton until that mode's reply lands.
  const [loaded, setLoaded] = useState({ mode: null });
  const [promotion, setPromotion] = useState(null);
  const [promotionFailed, setPromotionFailed] = useState(false);
  const [live, setLive] = useState([]);
  const [openName, setOpenName] = useState(null);
  const [filter, setFilter] = useState('');
  const [research, setResearch] = useState('record');
  const tradesOpen = research === 'trades';
  const [trades, setTrades] = useState({ mode: null });
  const [built, setBuilt] = useState(null);
  const loadBuilt = useCallback(
    () => api.get(endpoints.builtStrategies, { cache: false }).then((res) => setBuilt(res.data)).catch(() => setBuilt((b) => b || {})), []);
  useEffect(() => { loadBuilt(); }, [loadBuilt]);
  const mineSlugs = new Set(Object.values(built || {}).flat().filter((r) => r.mine).map((r) => `built:${r.slug}`));

  const loadLibrary = useCallback(() => {
    api.get(endpoints.strategyLibrary(mode))
      .then((res) => setLoaded({ mode, cards: res.data?.strategies ?? [] }))
      .catch(() => setLoaded({ mode, failed: true }));
  }, [mode]);
  useEffect(() => { loadLibrary(); }, [loadLibrary]);
  const cards = loaded.mode === mode ? loaded.cards ?? null : null;

  const loadPromotion = () =>
    api.get(endpoints.settings.promotion)
      .then((res) => {
        setPromotion(Object.fromEntries((res.data ?? []).map((row) => [row.name, row])));
        setPromotionFailed(false);
      })
      .catch(() => setPromotionFailed(true));
  useEffect(() => {
    loadPromotion();
    getPreferences().then((res) => setLive(res.data?.live_strategies || [])).catch(() => {});
  }, []);
  useTopic('trades', loadPromotion);
  useReconnect(loadPromotion);

  // Every paper trade loads only once opened.
  useEffect(() => {
    if (!tradesOpen) return;
    api.get(endpoints.trading.trades(null, 'paper', book.mode))
      .then((res) => setTrades({ mode: book.key, rows: res.data }))
      .catch((err) => setTrades({ mode: book.key, error: err?.response?.data?.detail || 'Could not reach the ledger' }));
  }, [tradesOpen, book.key, book.mode]);
  const tradesNow = trades.mode === book.key ? trades : { rows: null };

  const gate = (name) =>
    promotion ? readiness(promotion[name], live.includes(name)) : promotionFailed ? 'Couldn’t load what it still needs. Retry below.' : '…';
  const count = (status) => (cards || []).filter((c) => !status || statusOf(c) === status).length;
  const shown = (cards || []).filter((c) => !filter || statusOf(c) === filter);

  return (
    <SettingsPage title="Strategies" back="/settings/lab" backLabel="Lab" right={<Badge kind="paper">Paper</Badge>}>
      <div className="private space-y-3">
        <p className="text-[14px] text-[var(--text-muted)]">
          The autopilot trades only the weekly rotation. Everything below is research on paper: a strategy reaches real money
          only through its live gate. <Link to="/ai" className="whitespace-nowrap font-semibold text-[var(--accent)] underline-offset-4 hover:underline">AI scoreboard ›</Link>
        </p>
        <RotationScorecard />

        <section className="space-y-3 pt-2" aria-labelledby="library-heading">
          <div className="flex items-center justify-between gap-3">
            <h2 id="library-heading" className="text-[17px] font-bold text-[var(--text)]">Strategy library</h2>
            <Link to="/lab/limits" className="text-[14px] font-semibold text-[var(--accent)] min-h-11 inline-flex items-center">Live switches ›</Link>
          </div>
          <Tabs tabs={BOOKS.map((b) => ({ id: b.key, label: b.label }))} value={book.key} onChange={pickBook} label="Timeframe" />
          {cards?.length > 0 && (
            <div role="group" aria-label="Filter by status" className="flex gap-1.5 overflow-x-auto">
              {FILTERS.map(([status, label]) => (
                <button key={status || 'all'} type="button" aria-pressed={filter === status} onClick={() => setFilter(status)}
                        className={cn('tap shrink-0 min-h-11 px-3.5 rounded-full text-[14px] font-medium',
                          filter === status ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]')}>
                  {label} <span className="tabular-nums opacity-80">{count(status)}</span>
                </button>
              ))}
            </div>
          )}
          {loaded.mode === mode && loaded.failed ? (
            <ErrorLine message="Couldn’t load the strategies." onRetry={() => { setLoaded({ mode: null }); loadLibrary(); }} />
          ) : cards === null ? <Skeleton rows={5} /> : cards.length === 0 ? (
            <Empty title={mode ? 'No strategies in this timeframe' : 'No strategies yet'} body="Build your own under Mine below."
                   action={mode && <button type="button" onClick={() => pickBook('all')} className="min-h-11 px-3 font-semibold text-[var(--accent)]">Show all</button>} />
          ) : shown.length === 0 ? (
            <Empty title="None with this status" action={<button type="button" onClick={() => setFilter('')} className="min-h-11 px-3 font-semibold text-[var(--accent)]">Show all</button>} />
          ) : (
            <ul className="space-y-2">
              {shown.map((card) => (
                <StrategyItem key={card.name} card={card} gate={gate(card.name)} row={promotion?.[card.name]} gateKnown={!!promotion} open={openName === card.name}
                              onToggle={() => setOpenName((n) => (n === card.name ? null : card.name))} yours={mineSlugs.has(card.name)} />
              ))}
            </ul>
          )}
          {promotionFailed && <ErrorLine message="Couldn’t load what each strategy still needs." onRetry={loadPromotion} />}
          <p className="text-[12px] text-[var(--text-muted)]">Every strategy trades on paper first. It earns its live switch after a passing backtest plus enough paper days and trades.</p>
        </section>

        <section className="space-y-3 pt-4" aria-labelledby="research-heading">
          <h2 id="research-heading" className="text-[17px] font-bold text-[var(--text)]">Research</h2>
          <Tabs tabs={RESEARCH} value={research} onChange={setResearch} label="Research" />
          <div className="fade-in" key={research}>
            {research === 'record' && <Scorecard mode={book.mode} />}
            {research === 'mine' && <MyStrategies built={built} refresh={loadBuilt} />}
            {research === 'rejected' && <Rejected rows={(built?.rejected || []).filter((r) => !r.mine)} />}
            {research === 'trades' && (
              <TradeLedger title={book.mode ? `${book.label} trades` : 'Paper trades'} trades={tradesNow.rows || []}
                           loading={!tradesNow.rows && !tradesNow.error} error={tradesNow.error || null} />
            )}
            {research === 'learned' && <LearningSheet />}
          </div>
        </section>
      </div>
    </SettingsPage>
  );
};

export default Strategies;
