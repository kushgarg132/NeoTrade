import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Layout from '../components/Layout';
import EngineNow from '../components/paper/EngineNow';
import TodayNet from '../components/paper/TodayNet';
import TradedToday from '../components/paper/TradedToday';
import MoneyBadge from '../components/common/MoneyBadge';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import { Sheet, Ruling, Money } from '../components/doc/Doc';
import api, { endpoints, getPreferences } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { formatCurrency } from '../utils/formatters';

/** AI → Overview: the account the app runs, at a glance -- the autopilot and
    its capital, what the engine is doing now, today's paper money net of
    charges, and what it traded today. You vs the AI is on Today. */
const AiOverview = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const [data, setData] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(true);
  const loadPnl = () =>
    api.get(endpoints.analytics.pnl('paper'))
      .then((res) => setPnl(res.data))
      .catch(() => setPnl(null))
      .finally(() => setPnlLoading(false));
  useEffect(() => {
    api.get(endpoints.today).then((res) => setData(res.data)).catch(() => setData({}));
    getPreferences().then((res) => setPrefs(res.data)).catch(() => setPrefs(null));
    loadPnl();
  }, []);
  useTopic('pnl', (message) => message.data?.paper && setPnl(message.data.paper));
  useReconnect(loadPnl);
  const ap = data?.autopilot;
  const used = ap?.capital ? Math.min(100, (ap.deployed / ap.capital) * 100) : 0;
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={AI_TABS} label="AI account" />
        <Sheet title="Autopilot" meta={ap ? (ap.enabled ? `On · ${ap.live ? 'live' : 'paper'}` : 'Off') : undefined}
               actions={isAdmin && <Link to="/lab/limits" className="field-label text-[var(--stamp)] hover:underline">Settings ›</Link>}>
          {!data ? <Ruling rows={3} /> : !ap ? (
            <p className="doc-meta normal-case">Couldn’t load the autopilot.</p>
          ) : (
            <>
              <p className="text-sm"><MoneyBadge kind="ai" mode={ap.live ? 'live' : 'paper'} /> {formatCurrency(ap.deployed)} of {formatCurrency(ap.capital)} deployed</p>
              <div className="h-1.5 mt-2 bg-[var(--paper-sunk)]" aria-hidden="true">
                <div className="h-full" style={{ width: `${used}%`, background: 'var(--ai)' }} />
              </div>
              <p className="field-label mt-3 mb-1">Today, closed, net of charges</p>
              <Money value={data.scoreboard?.today?.ai} size="lg" />
              {!ap.enabled && (
                <p className="doc-meta normal-case mt-2">The autopilot is off. Turn it on under Settings once an AI account is set.</p>
              )}
            </>
          )}
        </Sheet>
        <EngineNow prefs={prefs} />
        <TodayNet pnl={pnl} loading={pnlLoading} />
        <TradedToday />
      </div>
    </Layout>
  );
};

export default AiOverview;
