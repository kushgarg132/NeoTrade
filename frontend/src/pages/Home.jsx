import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bot, ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Skeleton from '../components/ui/Skeleton';
import Card from '../components/ui/Card';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import HeroRow from '../components/home/HeroRow';
import TodayCard from '../components/home/TodayCard';
import GoalTile from '../components/home/GoalTile';
import WeeklyLink from '../components/home/WeeklyLink';
import NeedsYou from '../components/home/NeedsYou';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import SetupChecklist from '../components/home/SetupChecklist';
import api, { endpoints } from '../utils/api';
import { useReconnect, useRefetchOn } from '../hooks/useStream';
import { useAuth } from '../context/AuthContext';
import { useNeedCount } from '../hooks/useNeedCount';
import { aiBook } from '../utils/ai';
import { tileHeadlines, phaseLabel, briefKind, alerts, todayTitle, nextOpenLabel } from '../utils/home';
import { REFRESH_FAILED } from '../utils/formatters';

/** An expired-login alert goes straight to that broker's login, in this tab: iOS blocks a pop-up opened
 * after an await, and the broker's redirect lands on Settings -> Accounts, which finishes the connect.
 * If the URL cannot be built, the link's own target (Accounts) still opens. */
const openBrokerLogin = (e, a) => {
  e.preventDefault();
  api.get(endpoints.broker.loginUrl(a.login))
    .then((res) => window.location.assign(res.data.url))
    .catch(() => window.location.assign(a.to));
};

// Home: a hub. One call each for today, the account overview and the indices.
// A failing call keeps its tile's last figure and marks it "Couldn't refresh".
const Home = () => {
  const [today, setToday] = useState(null);
  const [overview, setOverview] = useState(null);
  const [indices, setIndices] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [card, setCard] = useState(null);
  const [day, setDay] = useState(undefined); // undefined until the AI day summary has answered (null = none)
  const [error, setError] = useState(null);
  const [failed, setFailed] = useState({}); // tile -> its last refresh failed
  const need = useNeedCount();
  const isAdmin = useAuth().user?.role === 'admin';
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
    api.get(endpoints.summaries.day).then((r) => setDay(r.data.summary ?? null)).catch(() => setDay((d) => d ?? null)); // the digest stands in
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
    const rows = Array.isArray(indices) ? indices : [];
    const nifty = rows.find((r) => r.name === 'NIFTY 50');
    const kind = briefKind(today.phase);
    const headline = overview?.headline || today.pulse;
    const opens = today.phase !== 'session' && nextOpenLabel(today.next_open);
    return (
      <div className="space-y-5">
        <div className="space-y-2">
          <p className="flex items-center gap-2 min-h-8 text-[14px] font-medium text-[var(--text-muted)]">
            <span aria-hidden="true" className={`w-2 h-2 rounded-full ${today.phase === 'session' ? 'bg-[var(--gain)]' : 'bg-[var(--text-muted)]'}`} />
            {phaseLabel(today.phase)}{opens && ` · ${opens}`}
          </p>
          {alerts(today).map((a) => (
            <Link key={a.id} to={a.to} role="alert" onClick={a.login ? (e) => openBrokerLogin(e, a) : undefined}
                  style={{ background: 'var(--loss-soft)' }}
                  className="flex items-center justify-between gap-3 min-h-11 rounded-[12px] px-3 py-2 text-[14px] font-medium text-[var(--loss)] tap">
              <span>{a.text}</span>
              <span className="shrink-0 font-semibold underline">{a.action}</span>
            </Link>
          ))}
        </div>
        <HeroRow headline={headline} nifty={nifty} phase={today.phase} failed={failed.money} onRetry={load} meta={meta('money', h.money.meta)}>
          <GoalTile compact />
        </HeroRow>
        <SetupChecklist setup={today.setup} />
        <NeedsYou need={need} isAdmin={isAdmin} onDone={load} />
        {/* Its moves and lines come from three answers; drawn once they are all in, not swapped a second later. */}
        {day !== undefined && (overview || failed.money)
          ? <TodayCard moves={headline?.news_moves} kind={kind} text={kind ? today[kind] : undefined} summary={day} />
          : <Card title={todayTitle(kind)}><Skeleton rows={3} /></Card>}
        <section aria-label="You, the AI and the market" className="space-y-2">
          <Link to="/ai" className="tap flex items-center gap-3 min-h-14 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
            <Bot className="w-5 h-5 shrink-0 text-[var(--accent)]" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[15px] font-semibold text-[var(--text)]">
                AI account <Badge kind={today.autopilot?.live ? 'live' : 'paper'}>{today.autopilot?.live ? 'Live' : 'Paper'}</Badge>
              </div>
              <div className="text-[13px] tabular-nums text-[var(--text-muted)] truncate">
                {h.ai.value === '—' ? 'Start the AI account' : <><span className="private">{h.ai.value}</span> · <span className={toneText(h.ai.subTone)}>{h.ai.sub}</span></>}
                {failed.ai && ` · ${REFRESH_FAILED.text}`}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
          </Link>
          {rows.length > 0 && (
            <Link to="/market" aria-label="Market: the indices" className="tap -mx-1 flex gap-2 overflow-x-auto px-1 pb-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[12px]">
              {rows.map((r) => (
                <span key={r.name} className="shrink-0 rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-3 py-2">
                  <span className="block text-[12px] text-[var(--text-muted)] whitespace-nowrap">{r.name}</span>
                  <span className={`block text-[15px] font-semibold tabular-nums ${toneText(tone(r.percent))}`}>{pct(r.percent / 100, { sign: true })}</span>
                </span>
              ))}
            </Link>
          )}
        </section>
        <WeeklyLink />
      </div>
    );
  };

  return (
    <Layout>
      <PageHeader title="Today" />
      {body()}
    </Layout>
  );
};

export default Home;
