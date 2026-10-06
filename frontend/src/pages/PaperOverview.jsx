import React, { useEffect, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import EngineNow from '../components/paper/EngineNow';
import TodayNet from '../components/paper/TodayNet';
import TradedToday from '../components/paper/TradedToday';
import api, { endpoints, getPreferences } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { statusOf } from '../utils/library';

/**
 * Practice → Engine: what the strategy engine is doing right now -- its two
 * engines, today's practice money net of charges, and what it traded today.
 * How the money has done over time is Book; whether any strategy is good
 * enough is Strategies.
 */
const StrategiesLine = () => {
  const [counts, setCounts] = useState(null);
  useEffect(() => {
    Promise.all(['INTRADAY', 'LONGTERM'].map((mode) => api.get(endpoints.strategyLibrary(mode))))
      .then((replies) => {
        const cards = replies.flatMap((res) => res.data.strategies);
        setCounts({ all: cards.length, ready: cards.filter((card) => statusOf(card) === 'live-ready').length });
      })
      .catch(() => setCounts(null));
  }, []);
  return (
    <Link to="/practice/strategies" className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)]">
      <span className="text-sm">
        <span className="field-label">Strategies</span>
        {counts ? ` · ${counts.all} strategies · ${counts.ready} ready for real money` : ' · which are good enough for real money'}
      </span>
      <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
    </Link>
  );
};

const PaperOverview = () => {
  const [params] = useSearchParams();
  const [pnl, setPnl] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(true);
  // Fetched once and handed to the engine sheets, so they agree on what is live.
  const [prefs, setPrefs] = useState(null);

  const loadPnl = () =>
    api.get(endpoints.analytics.pnl('paper'))
      .then((res) => setPnl(res.data))
      .catch(() => setPnl(null))
      .finally(() => setPnlLoading(false));
  useEffect(() => {
    loadPnl();
    getPreferences().then((res) => setPrefs(res.data)).catch(() => setPrefs(null));
  }, []);
  useTopic('pnl', (message) => message.data?.paper && setPnl(message.data.paper));
  useReconnect(loadPnl);

  // The track record moved to Strategies; old ?book= links follow it there.
  if (params.has('book')) return <Navigate to={`/practice/strategies?book=${params.get('book')}`} replace />;

  return (
    <Layout>
      <PaperShell>
        <EngineNow prefs={prefs} />
        <TodayNet pnl={pnl} loading={pnlLoading} />
        <TradedToday />
        <StrategiesLine />
      </PaperShell>
    </Layout>
  );
};

export default PaperOverview;
