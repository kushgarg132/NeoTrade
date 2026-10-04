import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import { Sheet, Ruling } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { formatDateTime } from '../utils/formatters';

/** AI → Activity: every autopilot order and refusal, newest first. */
const AiActivity = () => {
  const [rows, setRows] = useState(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    api.get(endpoints.settings.autopilotLog).then((res) => setRows(res.data.rows)).catch(() => setRows([]));
    api.get(endpoints.settings.preferences).then((res) => setOn(!!res.data.autopilot_enabled)).catch(() => {});
  }, []);
  const stop = () => api.put(endpoints.settings.preferences, { autopilot_enabled: false }).then(() => setOn(false));
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={AI_TABS} label="AI account" />
        <Sheet title="Activity" meta="Last 30"
               actions={on ? <button type="button" onClick={stop} className="h-8 px-3 text-xs border border-[var(--loss)] text-[var(--loss)]">🛑 Stop autopilot</button> : null}>
          {rows === null ? <Ruling rows={4} /> : rows.length === 0 ? (
            <p className="doc-meta normal-case">Nothing from the autopilot yet.</p>
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {rows.map((row, i) => (
                <li key={`${row.at}-${i}`} className="py-2.5 text-sm">
                  <span className={cn('field-label mr-2', row.status === 'FILLED' ? 'text-[var(--gain)]' : 'text-[var(--loss)]')}>{row.status}</span>
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
