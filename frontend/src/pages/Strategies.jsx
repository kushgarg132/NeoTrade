import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import Scorecard from '../components/paper/Scorecard';
import TradeLedger from '../components/dashboard/TradeLedger';
import LearningSheet from '../components/journal/LearningSheet';
import MyStrategies from '../components/strategies/MyStrategies';
import { Sheet, Ruling, Tabs } from '../components/doc/Doc';
import { Badge } from '../components/common/Badge';
import api, { endpoints, getPreferences } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { builtLine, recordLine, statusOf, strategyName } from '../utils/library';
import { readiness, shortStatus } from '../utils/promotion';
import { cn } from '../utils/cn';

/**
 * Practice → Strategies: is any strategy good enough for real money? Each
 * strategy's paper record and what it still needs, then the full track record
 * (net of charges, against NIFTY) and what the engine learned.
 */

const STATUS = {
  'live-ready': { label: 'Ready for real money', variant: 'success' },
  paper: { label: 'Paper', variant: 'secondary' },
  untested: { label: 'Not backtested', variant: 'secondary' },
  paused: { label: 'Paused by learning', variant: 'destructive' },
};
const SUMMARY = [['live-ready', 'ready for real money'], ['paper', 'paper'], ['untested', 'not backtested'], ['paused', 'paused']];

/** The track record's filter, kept in ?book= so old Engine links land here. */
const BOOKS = [
  { key: 'all', label: 'All', mode: undefined },
  { key: 'intraday', label: 'Intraday', mode: 'INTRADAY' },
  { key: 'longterm', label: 'Long term', mode: 'LONGTERM' },
];

const StrategyItem = ({ card, gate, short, open, onToggle, yours }) => {
  const status = STATUS[statusOf(card)];
  return (
    <li className="py-2.5">
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left min-h-11">
        <span className="flex flex-wrap items-baseline gap-2">
          <span className="figure-md text-sm">{strategyName(card.built ? card.name.replace(/^built:/, '') : card.name)}</span>
          <Badge variant={status.variant}>{status.label}</Badge>
          {card.built && <Badge variant="secondary">{yours ? 'Built · Yours' : 'Built'}</Badge>}
          {card.built && <Badge variant="neutral">{card.built.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>}
          <ChevronDown className={cn('ml-auto w-4 h-4 text-[var(--ink-faint)] transition-transform', open && 'rotate-180')} />
        </span>
        {card.built && (
          <span className="block text-sm mt-0.5">
            {card.built.description} — {card.built.thesis}
            <span className="block doc-meta normal-case">{builtLine(card.built.metrics, card.built.horizon)}</span>
          </span>
        )}
        <span className="block doc-meta normal-case mt-0.5">{recordLine(card)}</span>
        <span className="block text-sm mt-0.5">{short}</span>
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
          <p className="text-sm">{gate}</p>
          <p className="text-sm">{card.card.best_when}</p>
          <p className="doc-meta normal-case">Avoid: {card.card.avoid_when}</p>
          <p className="doc-meta normal-case">
            {card.card.style} · suits {card.card.regimes.join(', ').replace(/_/g, '-')}
            {card.card.needs.length > 0 && ` · needs ${card.card.needs.join(', ').replace(/_/g, ' ')}`}
          </p>
        </div>
      )}
    </li>
  );
};

/** The weekly builder's (not the user's own, those are in Mine) drafts that failed a check, so a rejected idea is never re-proposed unseen. */
const Rejected = ({ rows }) => {
  if (!rows?.length) return null;
  return (
    <details>
      <summary className="sheet cursor-pointer px-4 py-3 field-label">Tried and rejected</summary>
      <ul className="sheet divide-y divide-[var(--rule)] px-4 mt-3 sm:mt-4">
        {rows.map((r) => (
          <li key={r.slug} className="py-2.5">
            <Badge variant="neutral">{r.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>
            <span className="block text-sm">{[r.description, r.thesis].filter(Boolean).join(' — ') || r.verdict}</span>
            <span className="block doc-meta normal-case">{builtLine(r.metrics, r.horizon)}</span>
            <span className="block doc-meta normal-case">{r.verdict}</span>
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
    () => api.get(endpoints.builtStrategies).then((res) => setBuilt(res.data)).catch(() => setBuilt((b) => b || {})), []);
  useEffect(() => { loadBuilt(); }, [loadBuilt]);
  const mineSlugs = new Set(Object.values(built || {}).flat().filter((r) => r.mine).map((r) => `built:${r.slug}`));

  useEffect(() => {
    api.get(endpoints.strategyLibrary(mode))
      .then((res) => setLoaded({ mode, cards: res.data.strategies }))
      .catch(() => setLoaded({ mode, failed: true }));
  }, [mode]);
  const cards = loaded.mode === mode ? loaded.cards ?? null : null;

  const loadPromotion = () =>
    api.get(endpoints.settings.promotion)
      .then((res) => {
        setPromotion(Object.fromEntries(res.data.map((row) => [row.name, row])));
        setPromotionFailed(false);
      })
      .catch(() => setPromotionFailed(true));
  useEffect(() => {
    loadPromotion();
    getPreferences().then((res) => setLive(res.data.live_strategies || [])).catch(() => {});
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
    promotion ? readiness(promotion[name], live.includes(name)) : promotionFailed ? 'Couldn’t load what it still needs.' : '…';
  const short = (name) =>
    promotion ? shortStatus(promotion[name]).replace(/^ready$/, 'Ready for real money') : promotionFailed ? 'Couldn’t load what it still needs.' : '…';
  const counts = cards ? SUMMARY.map(([s, label]) => [cards.filter((c) => statusOf(c) === s).length, label]).filter(([n]) => n) : [];

  return (
    <Layout>
      <PaperShell>
        <Sheet
          title="Strategies"
          meta={cards ? counts.map(([n, label]) => `${n} ${label}`).join(' · ') : undefined}
          actions={<Link to="/practice/setup" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">Live switches ›</Link>}
        >
          <Tabs tabs={[{ id: 'INTRADAY', label: 'Intraday' }, { id: 'LONGTERM', label: 'Long-term' }]}
                active={mode} onSelect={setMode} label="Strategy timeframe" className="static z-auto mb-1" />
          {loaded.mode === mode && loaded.failed ? <p className="text-sm py-2">Couldn’t load the strategies.</p> : cards === null ? <Ruling rows={5} /> : (
            <ul className="divide-y divide-[var(--rule)]">
              {cards.map((card) => (
                <StrategyItem key={card.name} card={card} gate={gate(card.name)} short={short(card.name)} open={openName === card.name}
                              onToggle={() => setOpenName((n) => (n === card.name ? null : card.name))} yours={mineSlugs.has(card.name)} />
              ))}
            </ul>
          )}
        </Sheet>

        <div className="grid grid-cols-3 border border-[var(--rule-strong)]" role="tablist" aria-label="Which engine's record">
          {BOOKS.map((b) => (
            <button key={b.key} type="button" role="tab" aria-selected={b.key === book.key}
                    onClick={() => setParams(b.key === 'all' ? {} : { book: b.key }, { replace: true })}
                    className={cn('min-h-11 field-label touch-manipulation',
                      b.key === book.key ? 'bg-[var(--ink)] text-[var(--paper)]' : 'text-[var(--ink-soft)] hover:text-[var(--ink)]')}>
              {b.label}
            </button>
          ))}
        </div>
        <Scorecard mode={book.mode} />

        <MyStrategies built={built} refresh={loadBuilt} />

        <Rejected rows={(built?.rejected || []).filter((r) => !r.mine)} />

        <details onToggle={(event) => setTradesOpen(event.currentTarget.open)}>
          <summary className="sheet cursor-pointer px-4 py-3 field-label">Every paper trade</summary>
          {tradesOpen && (
            <div className="mt-3 sm:mt-4">
              <TradeLedger title={book.mode ? `${book.label} trades` : 'Paper trades'} trades={tradesNow.rows || []}
                           loading={!tradesNow.rows && !tradesNow.error} error={tradesNow.error || null} />
            </div>
          )}
        </details>

        <details onToggle={(event) => setLearningOpen(event.currentTarget.open)}>
          <summary className="sheet cursor-pointer px-4 py-3 field-label">What the engine learned</summary>
          {learningOpen && <div className="mt-3 sm:mt-4"><LearningSheet /></div>}
        </details>
      </PaperShell>
    </Layout>
  );
};

export default Strategies;
