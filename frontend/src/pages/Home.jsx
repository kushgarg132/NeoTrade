import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bot, Newspaper, ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tile from '../components/ui/Tile';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import HeroRow from '../components/home/HeroRow';
import BriefCard from '../components/home/BriefCard';
import GoalTile from '../components/home/GoalTile';
import WeeklyLink from '../components/home/WeeklyLink';
import SetupChecklist from '../components/home/SetupChecklist';
import api, { endpoints } from '../utils/api';
import { useReconnect, useRefetchOn } from '../hooks/useStream';
import { useNeedCount } from '../hooks/useNeedCount';
import { aiBook } from '../utils/ai';
import { tileHeadlines, phaseLabel, briefKind, alerts } from '../utils/home';
import { REFRESH_FAILED } from '../utils/formatters';

// Home: a hub. One call each for today, the account overview and the indices.
// A failing call keeps its tile's last figure and marks it "Couldn't refresh".
const Home = () => {
  const [today, setToday] = useState(null);
  const [overview, setOverview] = useState(null);
  const [indices, setIndices] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [card, setCard] = useState(null);
  const [day, setDay] = useState(null);
  const [error, setError] = useState(null);
  const [failed, setFailed] = useState({}); // tile -> its last refresh failed
  const need = useNeedCount();
  const reloadNeed = need.reload;

  const load = useCallback(() => {
    const track = (tile, request, set) => request
      .then((r) => { set(r.data); setFailed((f) => ({ ...f, [tile]: false })); })
      .catch(() => setFailed((f) => ({ ...f, [tile]: true })));
    api.get(endpoints.today).then((r) => { setToday(r.data); setError(null); })
      .catch((e) => setError(e?.response?.data?.detail || 'Could not load today.'));
    track('money', api.get(endpoints.mine.overview), setOverview);
    track('ai', api.get(endpoints.analytics.pnl('paper')), setPnl);
    track('ai', api.get(endpoints.analytics.scorecard('paper')), setCard);
    track('market', api.get(endpoints.marketIndices), setIndices);
    api.get(endpoints.summaries.day).then((r) => setDay(r.data.summary)).catch(() => {}); // the digest below stands in
    reloadNeed();
  }, [reloadNeed]);
  useEffect(() => {
    load();
    const timer = setInterval(() => !document.hidden && load(), 60_000);
    return () => clearInterval(timer);
  }, [load]);
  useReconnect(load);
  // A fill, a new idea or a fresh holdings snapshot shows now, not at the next poll.
  useRefetchOn(['trades', 'suggestions', 'autopilot', 'portfolio', 'guardrails'], load);

  const body = () => {
    if (!today) {
      return error
        ? <ErrorLine message={error} onRetry={load} />
        : <Skeleton rows={4} />;
    }
    const h = tileHeadlines(today, overview, indices, need.loaded ? need : null, aiBook({ autopilot: today.autopilot, pnl, card }));
    const meta = (tile, m) => (failed[tile] || (tile === 'ideas' && need.error) ? REFRESH_FAILED : m);
    const nifty = (Array.isArray(indices) ? indices : []).find((r) => r.name === 'NIFTY 50');
    const kind = briefKind(today.phase);
    const needs = need.count;
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center min-h-11 text-[14px] font-medium text-[var(--text-muted)]">{phaseLabel(today.phase)}</span>
          {needs > 0 && (
            <Link to="/ideas" title={h.ideas.sub}
                  className="ml-auto inline-flex items-center gap-1 min-h-11 px-4 rounded-full bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold active:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
              {needs} need{needs === 1 ? 's' : ''} you
              <ChevronRight className="w-4 h-4" aria-hidden="true" />
            </Link>
          )}
        </div>
        <HeroRow headline={overview?.headline || today.pulse} nifty={nifty} phase={today.phase} meta={meta('money', h.money.meta)} />
        {alerts(today).map((a) => (
          <Link key={a.id} to={a.to} role="alert"
                className="flex items-center justify-between gap-3 min-h-11 rounded-[12px] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2 text-[14px] font-medium text-[var(--loss)]">
            <span>{a.text}</span>
            <span className="shrink-0 font-semibold underline">{a.action}</span>
          </Link>
        ))}
        <SetupChecklist setup={today.setup} />
        <div className="grid grid-cols-2 gap-3">
          <Tile title={<>AI <Badge kind="paper">Paper</Badge></>} icon={Bot} to="/ai" value={h.ai.value} sub={h.ai.value === '—' ? 'Start the AI account' : h.ai.sub} tone={h.ai.tone} subTone={h.ai.subTone} meta={meta('ai', null)} />
          <Tile title="Market" icon={Newspaper} to="/market" value={h.market.value} sub={h.market.value === '—' ? 'Open Market' : h.market.sub} tone={h.market.tone} meta={meta('market', h.market.meta)} />
        </div>
        {kind && <BriefCard title={kind === 'premarket' ? 'Before the open' : 'After the close'} text={today[kind]} summary={day} />}
        <GoalTile />
        <WeeklyLink />
      </div>
    );
  };

  return (
    <Layout>
      <PageHeader title="Home" />
      {body()}
    </Layout>
  );
};

export default Home;
