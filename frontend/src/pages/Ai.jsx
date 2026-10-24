import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Badge from '../components/ui/Badge';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Scoreboard from '../components/ai/Scoreboard';
import Positions from '../components/ai/Positions';
import Activity from '../components/ai/Activity';
import StopAi from '../components/ai/StopAi';
import { useForward } from '../components/ForwardBadge';
import api, { endpoints } from '../utils/api';
import { useRefetchOn, useReconnect, useTopic } from '../hooks/useStream';
import { inr, pct, tone } from '../components/ui/format';
import { aiBook } from '../utils/ai';
import { toneText } from '../components/ui/tone';

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
      <div className="mb-3 rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-4">
        {!today.loaded || !pnl.loaded ? <Skeleton rows={2} /> : (
          <>
            <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
              <span>AI book</span>
              <Badge kind={ap?.live ? 'live' : 'paper'}>{ap?.live ? 'Live' : 'Paper'}</Badge>
              {ap && <Badge kind={on ? 'proven' : 'neutral'}>{on ? 'Autopilot on' : 'Autopilot off'}</Badge>}
            </div>
            <div className="private figure-md text-[28px] leading-8 font-bold tabular-nums text-[var(--text)]">{inr(value)}</div>
            <div className={`private tabular-nums text-[17px] font-semibold ${toneText(tone(day))}`}>
              Today {inr(day, { sign: true })} ({pct(dayPct, { sign: true })})
            </div>
            <div className="mt-1 text-[13px] text-[var(--text-muted)]">
              {ap ? (ap.exposure_cap ? <span className="private">{inr(ap.deployed)} of {inr(ap.exposure_cap)} cap deployed</span> : 'No exposure cap set') : <ErrorLine message="Couldn't load the autopilot status." onRetry={today.retry} />}
            </div>
            {on && <div className="mt-3"><StopAi onStopped={() => { setStopped(true); today.reload(); }} /></div>}
            {ap && !on && <Link to="/settings?tab=limits" className="mt-2 inline-flex items-center min-h-11 text-[15px] font-semibold text-[var(--accent)]">Turn the autopilot on in Limits</Link>}
          </>
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
