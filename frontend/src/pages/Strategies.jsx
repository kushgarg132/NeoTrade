import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
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
import { readiness, shortStatus } from '../utils/promotion';
import ForwardBadge from '../components/ForwardBadge';
import { cn } from '../utils/cn';

/**
 * Practice → Strategies: is any strategy good enough for real money? Each
 * strategy's paper record and what it still needs, then the full track record
 * (net of charges, against NIFTY) and what the engine learned.
 */

const STATUS = {
  'live-ready': { label: 'Passes the live gate', kind: 'proven' },
  paper: { label: 'Paper only', kind: 'paper' },
  untested: { label: 'Not backtested', kind: 'neutral' },
  paused: { label: 'Paused by learning', kind: 'alert' },
};
const SUMMARY = [['live-ready', 'pass the live gate'], ['paper', 'paper'], ['untested', 'not backtested'], ['paused', 'paused']];

/** The track record's filter, kept in ?book= so old Engine links land here. */
const BOOKS = [
  { key: 'all', label: 'All', mode: undefined },
  { key: 'intraday', label: 'Intraday', mode: 'INTRADAY' },
  { key: 'longterm', label: 'Long term', mode: 'LONGTERM' },
];

const StrategyItem = ({ card, gate, short, open, onToggle, yours }) => {
  const status = STATUS[statusOf(card)];
  const needs = statusOf(card) !== 'live-ready';
  return (
    <li className="py-2.5">
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left min-h-11">
        <span className="flex flex-wrap items-center gap-2">
          <span className="figure-md text-sm">{strategyName(card.built ? card.name.replace(/^built:/, '') : card.name)}</span>
          <Badge kind={status.kind}>{status.label}</Badge>
          <ForwardBadge source="engine" name={card.name} />
          <ChevronDown className={cn('ml-auto w-4 h-4 text-[var(--text-muted)] transition-transform', open && 'rotate-180')} />
        </span>
        <span className="flex items-center gap-2 mt-1 text-[13px] text-[var(--text-muted)]">
          <Badge kind="paper">Paper</Badge>
          <span className="min-w-0">{recordLine(card)}</span>
        </span>
        {needs && <span className="block text-[13px] text-[var(--text-muted)] mt-0.5">{short}</span>}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
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
const SUMMARY_CLS = 'cursor-pointer rounded-[16px] border border-[var(--border)] bg-[var(--surface)] px-4 min-h-11 flex items-center text-[15px] font-semibold text-[var(--text)]';

const Rejected = ({ rows }) => {
  if (!rows?.length) return null;
  return (
    <details>
      <summary className={SUMMARY_CLS}>Tried and rejected</summary>
      <ul className="rounded-[16px] border border-[var(--border)] bg-[var(--surface)] divide-y divide-[var(--border)] px-4 mt-3">
        <li className="py-2.5 text-[13px] text-[var(--text-muted)]">Ideas the weekly builder dropped after a failed check.</li>
        {rows.map((r) => (
          <li key={r.slug} className="py-2.5">
            <Badge kind="neutral">{r.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>
            <span className="block text-sm">{[r.description, r.thesis].filter(Boolean).join(' — ') || r.verdict}</span>
            <span className="block text-[13px] text-[var(--text-muted)]">{builtLine(r.metrics, r.horizon)}</span>
            <span className="block text-[13px] text-[var(--text-muted)]">{r.verdict}</span>
          </li>
        ))}
      </ul>
    </details>
  );
};

const Strategies = () => {
  const [params, setParams] = useSearchParams();
  const book = BOOKS.find((b) => b.key === params.get('book')) || BOOKS[0];
  const [mode, setMode] = useState(book.mode || 'INTRADAY');
  // Keyed by mode, so switching shows the skeleton until that mode's reply lands.
  const [loaded, setLoaded] = useState({ mode: null });
  const [promotion, setPromotion] = useState(null);
  const [promotionFailed, setPromotionFailed] = useState(false);
  const [live, setLive] = useState([]);
  const [openName, setOpenName] = useState(null);
  const [tradesOpen, setTradesOpen] = useState(false);
  const [trades, setTrades] = useState({ mode: null });
  const [learningOpen, setLearningOpen] = useState(false);
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
  const short = (name) =>
    promotion ? shortStatus(promotion[name]).replace(/^ready$/, 'Ready for real money') : promotionFailed ? 'Couldn’t load what it still needs.' : '…';
  const counts = cards ? SUMMARY.map(([s, label]) => [cards.filter((c) => statusOf(c) === s).length, label]).filter(([n]) => n) : [];

  return (
    <SettingsPage title="Strategies" back="/settings/lab" backLabel="Lab" right={<Badge kind="paper">Paper</Badge>}>
      <div className="private space-y-3">
        <Card
          title="Strategies"
          action={<Link to="/lab/limits" className="text-[14px] font-semibold text-[var(--accent)] min-h-11 inline-flex items-center">Live switches ›</Link>}
        >
          <p className="text-[13px] text-[var(--text-muted)] mb-3">
            {cards?.length ? `${counts.map(([n, label]) => `${n} ${label}`).join(' · ')}. ` : ''}
            Every strategy trades on paper first. It can earn its live switch after a passing backtest plus enough paper days and trades.
          </p>
          <Tabs tabs={[{ id: 'INTRADAY', label: 'Intraday' }, { id: 'LONGTERM', label: 'Long-term' }]}
                value={mode} onChange={setMode} label="Strategy timeframe" />
          <div className="mt-2">
            {loaded.mode === mode && loaded.failed ? (
              <ErrorLine message="Couldn’t load the strategies." onRetry={() => { setLoaded({ mode: null }); loadLibrary(); }} />
            ) : cards === null ? <Skeleton rows={5} /> : cards.length === 0 ? (
              <Empty title="No strategies in this timeframe" body="Build your own under Mine below, or switch the timeframe."
                     action={<button type="button" onClick={() => setMode(mode === 'INTRADAY' ? 'LONGTERM' : 'INTRADAY')} className="min-h-11 px-3 font-semibold text-[var(--accent)]">Show {mode === 'INTRADAY' ? 'long-term' : 'intraday'}</button>} />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {cards.map((card) => (
                  <StrategyItem key={card.name} card={card} gate={gate(card.name)} short={short(card.name)} open={openName === card.name}
                                onToggle={() => setOpenName((n) => (n === card.name ? null : card.name))} yours={mineSlugs.has(card.name)} />
                ))}
              </ul>
            )}
            {promotionFailed && <ErrorLine message="Couldn’t load what each strategy still needs." onRetry={loadPromotion} />}
          </div>
        </Card>

        <div className="grid grid-cols-3 rounded-[12px] overflow-hidden border border-[var(--border)]" role="tablist" aria-label="Which engine's record">
          {BOOKS.map((b) => (
            <button key={b.key} type="button" role="tab" aria-selected={b.key === book.key}
                    onClick={() => setParams(b.key === 'all' ? {} : { book: b.key }, { replace: true })}
                    className={cn('min-h-11 text-[14px] font-medium touch-manipulation',
                      b.key === book.key ? 'bg-[var(--text)] text-[var(--surface)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]')}>
              {b.label}
            </button>
          ))}
        </div>
        <Scorecard mode={book.mode} />

        <MyStrategies built={built} refresh={loadBuilt} />

        <Rejected rows={(built?.rejected || []).filter((r) => !r.mine)} />

        <details onToggle={(event) => setTradesOpen(event.currentTarget.open)}>
          <summary className={SUMMARY_CLS}>Every paper trade</summary>
          {tradesOpen && (
            <div className="mt-3">
              <TradeLedger title={book.mode ? `${book.label} trades` : 'Paper trades'} trades={tradesNow.rows || []}
                           loading={!tradesNow.rows && !tradesNow.error} error={tradesNow.error || null} />
            </div>
          )}
        </details>

        <details onToggle={(event) => setLearningOpen(event.currentTarget.open)}>
          <summary className={SUMMARY_CLS}>What the engine learned</summary>
          {learningOpen && <div className="mt-3"><LearningSheet /></div>}
        </details>
      </div>
    </SettingsPage>
  );
};

export default Strategies;
