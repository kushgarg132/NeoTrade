import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import PnlStatement from '../components/dashboard/PnlStatement';
import TradeLedger from '../components/dashboard/TradeLedger';
import Scorecard from '../components/paper/Scorecard';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';

/**
 * The paper book at a glance: what practice money made today and this month,
 * what is waiting for a decision, and what the engine is holding. None of it
 * is the broker account -- that is the statement's job.
 */
const PaperOverview = () => {
  const [pnl, setPnl] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(true);
  const [trades, setTrades] = useState([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState(null);
  const [pending, setPending] = useState([]);

  const loadTrades = () =>
    api
      .get(endpoints.trading.trades(null, 'paper'))
      .then((res) => {
        setTrades(res.data);
        setTradesError(null);
      })
      .catch((err) => setTradesError(err?.response?.data?.detail || 'Could not reach the ledger'))
      .finally(() => setTradesLoading(false));

  useEffect(() => {
    api
      .get(endpoints.analytics.pnl('paper'))
      .then((res) => setPnl(res.data))
      .catch(() => setPnl(null))
      .finally(() => setPnlLoading(false));

    loadTrades();

    api
      .get(endpoints.suggestions.list({ status: 'PENDING' }))
      .then((res) => setPending(res.data))
      .catch(() => setPending([]));
  }, []);

  useTopic('pnl', (message) => message.data?.paper && setPnl(message.data.paper));
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
            to="/paper/decisions"
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

        {/* The track record first: it is what decides whether a strategy
            has earned real money. Today's live figures follow it. */}
        <Scorecard />

        <PnlStatement pnl={pnl} loading={pnlLoading} />

        <TradeLedger
          title="Paper trades"
          trades={trades}
          loading={tradesLoading}
          error={tradesError}
        />
      </PaperShell>
    </Layout>
  );
};

export default PaperOverview;
