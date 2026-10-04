import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import PnlStatement from '../components/dashboard/PnlStatement';
import TradeLedger from '../components/dashboard/TradeLedger';
import Scorecard from '../components/paper/Scorecard';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import { cn } from '../utils/cn';

/** The whole paper book, or one engine's share of it. */
const BOOKS = [
  { key: 'all', label: 'All', mode: undefined },
  { key: 'intraday', label: 'Intraday', mode: 'INTRADAY' },
  { key: 'longterm', label: 'Long term', mode: 'LONGTERM' },
];

/**
 * The paper book at a glance: what practice money made today and this month,
 * what is waiting for a decision, and what the engine is holding. None of it
 * is the broker account -- that is the statement's job.
 */
const PaperOverview = () => {
  const [params, setParams] = useSearchParams();
  const book = BOOKS.find((b) => b.key === params.get('book')) || BOOKS[0];
  const { mode } = book;
  const [pnl, setPnl] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(true);
  const [trades, setTrades] = useState([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState(null);
  const [pending, setPending] = useState([]);

  const loadTrades = () =>
    api
      .get(endpoints.trading.trades(null, 'paper', mode))
      .then((res) => {
        setTrades(res.data);
        setTradesError(null);
      })
      .catch((err) => setTradesError(err?.response?.data?.detail || 'Could not reach the ledger'))
      .finally(() => setTradesLoading(false));

  const loadPnl = () =>
    api
      .get(endpoints.analytics.pnl('paper', mode))
      .then((res) => setPnl(res.data))
      .catch(() => setPnl(null))
      .finally(() => setPnlLoading(false));

  useEffect(() => {
    setPnlLoading(true);
    setTradesLoading(true);
    loadPnl();
    loadTrades();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  useEffect(() => {
    api
      .get(endpoints.suggestions.list({ status: 'PENDING' }))
      .then((res) => setPending(res.data))
      .catch(() => setPending([]));
  }, []);

  // The pushed figures are the whole book; one engine's share is refetched.
  useTopic('pnl', (message) => {
    if (!message.data?.paper) return;
    if (mode) loadPnl();
    else setPnl(message.data.paper);
  });
  useTopic('trades', loadTrades);
  useTopic('suggestions', (message) => {
    if (message.event === 'created') setPending((list) => [message.data, ...list]);
    if (message.event === 'decided') {
      setPending((list) => list.filter((item) => item.id !== message.data.id));
    }
  });

  return (
    <Layout>
      <PaperShell>
        {pending.length > 0 && (
          <Link
            to="/ai/practice/decisions"
            className="block sheet px-4 py-3.5 border-[var(--stamp)] hover:bg-[var(--stamp-soft)] transition-colors"
          >
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="field-label text-[var(--stamp)]">Awaiting your decision</p>
                <p className="mt-1 text-sm text-[var(--ink)] truncate">
                  {pending.length} {pending.length === 1 ? 'proposal' : 'proposals'} ·{' '}
                  {pending
                    .slice(0, 3)
                    .map((item) => item.symbol)
                    .join(', ')}
                  {pending.length > 3 && ` +${pending.length - 3}`}
                </p>
              </div>
              <ArrowRight className="w-5 h-5 shrink-0 text-[var(--stamp)]" />
            </div>
          </Link>
        )}

        <div className="grid grid-cols-3 border border-[var(--rule-strong)]" role="tablist" aria-label="Which engine">
          {BOOKS.map((b) => (
            <button
              key={b.key}
              type="button"
              role="tab"
              aria-selected={b.key === book.key}
              onClick={() => setParams(b.key === 'all' ? {} : { book: b.key }, { replace: true })}
              className={cn(
                'min-h-11 field-label touch-manipulation',
                b.key === book.key ? 'bg-[var(--ink)] text-[var(--paper)]' : 'text-[var(--ink-soft)] hover:text-[var(--ink)]'
              )}
            >
              {b.label}
            </button>
          ))}
        </div>

        {/* The track record first: it is what decides whether a strategy
            has earned real money. Today's live figures follow it. */}
        <Scorecard mode={mode} />

        <PnlStatement pnl={pnl} loading={pnlLoading} />

        <TradeLedger
          title={mode ? `${book.label} trades` : 'Paper trades'}
          trades={trades}
          loading={tradesLoading}
          error={tradesError}
        />
      </PaperShell>
    </Layout>
  );
};

export default PaperOverview;
