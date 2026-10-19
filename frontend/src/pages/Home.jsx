import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Wallet, Lightbulb, Bot, Newspaper } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tile from '../components/ui/Tile';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import BriefCard from '../components/home/BriefCard';
import GoalTile from '../components/home/GoalTile';
import WeeklyLink from '../components/home/WeeklyLink';
import SetupChecklist from '../components/home/SetupChecklist';
import api, { endpoints } from '../utils/api';
import { useReconnect, useRefetchOn } from '../hooks/useStream';
import { useNeedCount } from '../hooks/useNeedCount';
import { aiBook } from '../utils/ai';
import { tileHeadlines, phaseLabel, briefKind, alerts } from '../utils/home';

// Home: a hub. One call each for today, the account overview and the indices;
// a failing overview or index call only blanks its own figure.
const Home = () => {
  const [today, setToday] = useState(null);
  const [overview, setOverview] = useState(null);
  const [indices, setIndices] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [card, setCard] = useState(null);
  const [day, setDay] = useState(null);
  const [error, setError] = useState(null);
  const need = useNeedCount();

  const load = useCallback(() => {
    api.get(endpoints.today).then((r) => { setToday(r.data); setError(null); })
      .catch((e) => setError(e?.response?.data?.detail || 'Could not load today.'));
    api.get(endpoints.mine.overview).then((r) => setOverview(r.data)).catch(() => {});
    api.get(endpoints.analytics.pnl('paper')).then((r) => setPnl(r.data)).catch(() => {});
    api.get(endpoints.analytics.scorecard('paper')).then((r) => setCard(r.data)).catch(() => {});
    api.get(endpoints.marketIndices).then((r) => setIndices(r.data)).catch(() => {});
    api.get(endpoints.summaries.day).then((r) => setDay(r.data.summary)).catch(() => {}); // the digest below stands in
  }, []);
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
    const h = tileHeadlines(today, overview, indices, need, aiBook({ autopilot: today.autopilot, pnl, card }));
    const kind = briefKind(today.phase);
    const needs = need.count;
    return (
      <div className="space-y-3">
        <p className="text-[15px] text-[var(--text-muted)]">
          {phaseLabel(today.phase)}
          {needs > 0 && <> · <Link to="/ideas" className="font-semibold text-[var(--accent)]">{needs} need{needs === 1 ? 's' : ''} you</Link></>}
        </p>
        {alerts(today).map((a) => (
          <Link key={a.id} to={a.to} role="alert"
                className="flex items-center justify-between gap-3 min-h-11 rounded-[12px] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2 text-[14px] font-medium text-[var(--loss)]">
            <span>{a.text}</span>
            <span className="shrink-0 font-semibold underline">{a.action}</span>
          </Link>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <Tile title="Money" icon={Wallet} to="/money" value={h.money.value} sub={h.money.sub} tone={h.money.tone} subTone={h.money.subTone} />
          <Tile title="Ideas" icon={Lightbulb} to="/ideas" value={h.ideas.value} sub={h.ideas.sub} tone={h.ideas.tone} />
          <Tile title="AI" icon={Bot} to="/ai" value={h.ai.value} sub={h.ai.sub} tone={h.ai.tone} />
          <Tile title="Market" icon={Newspaper} to="/market" value={h.market.value} sub={h.market.sub} tone={h.market.tone} />
        </div>
        {kind && <BriefCard title={kind === 'premarket' ? 'Before the open' : 'After the close'} text={today[kind]} summary={day} />}
        <GoalTile />
        <WeeklyLink />
        <SetupChecklist setup={today.setup} />
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
