import React, { useCallback, useEffect, useRef, useState } from 'react';
import SettingsPage from './SettingsPage';
import Markdown from '../components/common/Markdown';
import SystemTabs from '../components/system/SystemTabs';
import LivePanel from '../components/system/LivePanels';
import { useTab } from '../hooks/useTab';
import { HANDBOOK_TABS, PANELS, splitLive } from '../utils/handbook';
import api, { endpoints } from '../utils/api';
import system from '../handbook/system-and-data.md?raw';
import trading from '../handbook/trading-and-money.md?raw';
import ai from '../handbook/ai-and-news.md?raw';
import ops from '../handbook/jobs-and-ops.md?raw';
import journey from '../handbook/journey.md?raw';

/**
 * The operator's handbook (admin-only): how NeoTrade works, written in
 * src/handbook/*.md, with live panels from GET /system/status where the
 * markdown marks them.
 */
const DOCS = { system, trading, ai, ops, journey };
// Reading column: 15px body, plain sans headings (not the old uppercase label), and on a phone a wide table
// scrolls inside itself and long code paths break, so the page never scrolls sideways.
const WIDE = '[&_pre]:overflow-x-auto [&_pre]:max-w-full [&_table]:block [&_table]:overflow-x-auto [&_table]:max-w-full [&_code]:[overflow-wrap:anywhere] ' +
  '[&_h2]:text-[18px] [&_h2]:font-bold [&_h2]:mt-6 [&_h3]:text-[15px] [&_h3]:font-semibold [&_h3]:mt-4 [&_h2]:leading-snug ' +
  '[&_h1]:text-[22px] [&_h1]:font-bold [&_table]:w-max [&_td]:min-w-[8rem] [&_td]:max-w-[16rem] [&_td]:align-top [&_td]:px-2 [&_th]:px-2 [&_table]:text-[13px] [&_th]:text-left [&_th]:whitespace-nowrap [&_td]:py-1 [&_th]:py-1 [&_code]:text-[13px] [&_pre]:text-[13px] [&_h2]:scroll-mt-16 [&_h3]:scroll-mt-16';
const plain = (text) => text.replace(/[`*_]/g, '').trim();

const Handbook = () => {
  const [tab, setTab] = useTab(HANDBOOK_TABS.map((t) => t.id));
  const [status, setStatus] = useState(null);
  const article = useRef(null);

  const load = useCallback(
    () =>
      api.get(endpoints.system.status)
        .then((res) => setStatus(res.data))
        .catch((err) => setStatus({ as_of: new Date().toISOString(), error: err?.response?.data?.detail || 'Could not read live status' })),
    []
  );
  const reload = () => {
    setStatus(null);
    load();
  };

  useEffect(() => {
    const onShow = () => document.visibilityState === 'visible' && load();
    load();
    document.addEventListener('visibilitychange', onShow);
    return () => document.removeEventListener('visibilitychange', onShow);
  }, [load]);

  const headings = [...DOCS[tab].matchAll(/^## (.+)$/gm)].map((m) => plain(m[1]));
  const jump = (text) =>
    [...(article.current?.querySelectorAll('h2') || [])].find((h) => h.textContent.trim() === text)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  return (
    <SettingsPage title="Handbook" back="/settings/lab" backLabel="Lab">
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <p className="text-[14px] text-[var(--text-muted)]">How NeoTrade works, checked against the code. Live status panels sit beside the topics they describe.</p>
        <SystemTabs active={tab} onSelect={setTab} />
        {headings.length > 1 && (
          <details className="rounded-[12px] border border-[var(--border)] bg-[var(--surface)]">
            <summary className="min-h-11 px-4 flex items-center text-[14px] font-medium cursor-pointer">On this page · {headings.length}</summary>
            <ul className="px-2 pb-2">
              {headings.map((h) => (
                <li key={h}>
                  <button type="button" onClick={() => jump(h)} className="w-full min-h-11 px-2 text-left text-[14px] text-[var(--accent)]">{h}</button>
                </li>
              ))}
            </ul>
          </details>
        )}
        <article ref={article} className="min-w-0 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4 sm:px-5 text-[15px] leading-relaxed">
          {splitLive(DOCS[tab], PANELS).map((part, index) =>
            part.live ? <LivePanel key={part.live} name={part.live} status={status} onRetry={reload} /> : <Markdown key={index} className={WIDE}>{part.md}</Markdown>
          )}
        </article>
      </div>
    </SettingsPage>
  );
};

export default Handbook;
