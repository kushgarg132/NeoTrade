import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import AiToday from '../components/decisions/AiToday';
import MoneyBadge from '../components/common/MoneyBadge';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import { Sheet, Ruling, Money } from '../components/doc/Doc';
import AiVsMeSheet from '../components/journal/AiVsMeSheet';
import api, { endpoints } from '../utils/api';
import { formatCurrency } from '../utils/formatters';

/** AI → Overview: the AI account's autopilot at a glance, and how it is doing
    against the trader and the Nifty. */
const AiOverview = () => {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get(endpoints.today).then((res) => setData(res.data)).catch(() => setData({}));
  }, []);
  const ap = data?.autopilot;
  const used = ap?.capital ? Math.min(100, (ap.deployed / ap.capital) * 100) : 0;
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={AI_TABS} label="AI account" />
        <Sheet title="Autopilot" meta={ap ? (ap.enabled ? `On · ${ap.live ? 'live' : 'paper'}` : 'Off') : undefined}
               actions={<Link to="/ai/autopilot" className="field-label text-[var(--stamp)] hover:underline">Autopilot ›</Link>}>
          {!data ? <Ruling rows={3} /> : !ap ? (
            <p className="doc-meta normal-case">Couldn’t load the autopilot.</p>
          ) : (
            <>
              <p className="text-sm"><MoneyBadge kind="ai" mode={ap.live ? 'live' : 'paper'} /> {formatCurrency(ap.deployed)} of {formatCurrency(ap.capital)} deployed</p>
              <div className="h-1.5 mt-2 bg-[var(--paper-sunk)]" aria-hidden="true">
                <div className="h-full" style={{ width: `${used}%`, background: 'var(--ai)' }} />
              </div>
              <p className="field-label mt-3 mb-1">Today, closed, net of charges</p>
              <Money value={data.pnl_today?.ai} size="lg" />
              {!ap.enabled && (
                <p className="doc-meta normal-case mt-2">The autopilot is off. Turn it on under Autopilot once an AI account is set.</p>
              )}
            </>
          )}
        </Sheet>
        <AiToday />
        <AiVsMeSheet />
      </div>
    </Layout>
  );
};

export default AiOverview;
