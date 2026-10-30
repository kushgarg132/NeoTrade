import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import ErrorLine from '../components/ui/ErrorLine';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import DeltaChip from '../components/ui/DeltaChip';
import Skeleton from '../components/ui/Skeleton';
import Scoreboard from '../components/ai/Scoreboard';
import Positions from '../components/ai/Positions';
import Activity from '../components/ai/Activity';
import StopAi from '../components/ai/StopAi';
import { useForward } from '../components/ForwardBadge';
import api, { endpoints } from '../utils/api';
import { useRefetchOn, useReconnect, useTopic } from '../hooks/useStream';
import { inr } from '../components/ui/format';
import { aiBook } from '../utils/ai';

const IDS = ['scoreboard', 'positions', 'activity'];
const TABS = [{ id: 'scoreboard', label: 'Scoreboard' }, { id: 'positions', label: 'Positions' }, { id: 'activity', label: 'Activity' }];

/** One independent fetch: a failing section never blanks the page. */
const useLoad = (fetcher) => {
  const [s, setS] = useState({ loaded: false, error: false, data: null });
  const load = useCallback(() => {
    fetcher().then((data) => setS({ loaded: true, error: false, data }))
      .catch(() => setS((p) => ({ ...p, loaded: true, error: true })));
  }, [fetcher]);
  useEffect(load, [load]);
  return { ...s, retry: () => { setS((p) => ({ ...p, loaded: false, error: false })); load(); }, reload: load };
};
const get = (url) => () => api.get(url).then((r) => r.data);
const f = {
  today: get(endpoints.today),
  pnl: get(endpoints.analytics.pnl('paper')),
  card: get(endpoints.analytics.scorecard('paper')),
  positions: get(endpoints.trading.positions('paper')),
  log: get(endpoints.settings.autopilotLog),
  overview: get(endpoints.mine.overview),
  plan: get(endpoints.planToday),
};

const Ai = () => {
  const [tab, setTab] = useTabParam(IDS);
  const today = useLoad(f.today);
  const pnl = useLoad(f.pnl);
  const card = useLoad(f.card);
  const positions = useLoad(f.positions);
  const log = useLoad(f.log);
  const overview = useLoad(f.overview);
  const plan = useLoad(f.plan);
  const forward = useForward();
  const [stopped, setStopped] = useState(false);

  useTopic('pnl', (m) => m.data?.paper && pnl.reload());
  useRefetchOn(['positions', 'trades'], () => { positions.reload(); card.reload(); });
  useRefetchOn(['autopilot'], log.reload);
  useReconnect(() => { today.reload(); pnl.reload(); });

  const ap = today.data?.autopilot;
  const on = ap?.enabled && !stopped;
  const { value, day, dayPct } = aiBook({ autopilot: ap, pnl: pnl.data, card: card.data });

  return (
    <Layout>
      <PageHeader title="AI" />
      <div className="mb-3">
        {!today.loaded || !pnl.loaded ? <Card><Skeleton rows={2} /></Card> : (
          <Hero label="AI book" value={value} change={<DeltaChip value={day} pct={typeof dayPct === 'number' ? dayPct * 100 : undefined} suffix="today" />}>
            {!ap ? <div className="mt-3"><ErrorLine message="Couldn't load the autopilot status." onRetry={today.retry} /></div> : (
              <>
                <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-[var(--border)] pt-3">
                  <span aria-hidden="true" className={`w-2 h-2 shrink-0 rounded-full ${on ? 'bg-[var(--gain)]' : 'bg-[var(--text-muted)]'}`} />
                  <span className="min-w-0 flex-1 text-[15px] font-semibold text-[var(--text)]">
                    {ap.live ? 'Live' : 'Paper'} · Autopilot {on ? 'on' : 'off'}
                  </span>
                  {on && <StopAi compact onStopped={() => { setStopped(true); today.reload(); }} />}
                  {!on && <Link to="/settings/autopilot" className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">Turn on</Link>}
                </div>
                {ap.exposure_cap ? (
                  <div className="mt-2">
                    <div className="h-1.5 rounded-full bg-[var(--surface-2)]" role="progressbar" aria-label="Deployed of the exposure cap"
                      aria-valuenow={Math.round(Math.min(1, (ap.deployed || 0) / ap.exposure_cap) * 100)} aria-valuemin={0} aria-valuemax={100}>
                      <div className="h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${Math.min(1, (ap.deployed || 0) / ap.exposure_cap) * 100}%` }} />
                    </div>
                    <div className="mt-1.5 text-[12px] tabular-nums text-[var(--text-muted)]"><span className="private">{inr(ap.deployed)} of {inr(ap.exposure_cap)}</span> cap deployed</div>
                  </div>
                ) : <div className="mt-2 text-[12px] text-[var(--text-muted)]">No exposure cap set</div>}
                {(ap.lab === false || ap.paused?.length > 0) && (
                  <p className="mt-2 text-[12px] text-[var(--text-muted)]">
                    {ap.lab === false && 'Lab off: no intraday auto-run, news entries or game plan.'}
                    {ap.paused?.length > 0 && ` Paused on paper (losing over 30+ trades): ${ap.paused.join(', ')}.`}
                  </p>
                )}
              </>
            )}
          </Hero>
        )}
      </div>
      <div className="mb-3"><Tabs tabs={TABS} value={tab} onChange={setTab} label="AI sections" /></div>
      {tab === 'scoreboard' && <Scoreboard board={{ ...today, data: today.data?.scoreboard }} card={card} forward={forward} capital={ap?.capital} mineValue={overview.data?.headline?.value} />}
      {tab === 'positions' && <Positions state={positions} />}
      {tab === 'activity' && <Activity state={log} plan={plan.data} />}
    </Layout>
  );
};

export default Ai;
