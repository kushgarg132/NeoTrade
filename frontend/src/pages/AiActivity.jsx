import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import { Sheet, Ruling } from '../components/doc/Doc';
import StopAutopilot from '../components/common/StopAutopilot';
import PlanCard from '../components/plan/PlanCard';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { formatDateTime } from '../utils/formatters';

/** AI → Activity: every autopilot order and refusal, newest first. */
const AiActivity = () => {
  const [rows, setRows] = useState(null);
  const [on, setOn] = useState(false);
  const [failed, setFailed] = useState(false);
  const load = () => {
    api.get(endpoints.settings.autopilotLog).then((res) => setRows(res.data.rows)).catch(() => setFailed(true));
  };
  const retry = () => {
    setFailed(false);
    setRows(null);
    load();
  };
  useEffect(() => {
    load();
    api.get(endpoints.settings.preferences).then((res) => setOn(!!res.data.autopilot_enabled)).catch(() => {});
  }, []);
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={AI_TABS} label="AI account" />
        <PlanCard />
        <Sheet title="Activity" meta="Last 30"
               actions={<StopAutopilot on={on} label="Stop autopilot" onStopped={() => setOn(false)} />}>
          {failed ? (
            <p className="text-sm">
              Couldn't load the autopilot's activity.{' '}
              <button type="button" onClick={retry} className="underline min-h-11">Retry</button>
            </p>
          ) : rows === null ? <Ruling rows={4} /> : rows.length === 0 ? (
            <p className="doc-meta normal-case">Nothing from the autopilot yet.</p>
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {rows.map((row, i) => (
                <li key={`${row.at}-${i}`} className="py-2.5 text-sm">
                  <span className={cn('field-label mr-2', row.status === 'FILLED' ? 'text-[var(--gain)]' : row.status === 'SENT' ? 'text-[var(--ink-soft)]' : 'text-[var(--loss)]')}>{row.status}</span>
                  {row.side} {row.quantity} {row.symbol}
                  <span className="doc-meta normal-case"> · {row.source} · {row.mode || ''} · {formatDateTime(row.at)}</span>
                  {row.reason && <p className="doc-meta normal-case mt-0.5">{row.reason}</p>}
                </li>
              ))}
            </ul>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default AiActivity;
