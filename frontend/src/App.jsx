import React, { Suspense, lazy, useEffect, useRef } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigate, useNavigationType, useParams } from 'react-router-dom';
const Strategies = lazy(() => import('./pages/Strategies'));
const OptionChain = lazy(() => import('./pages/OptionChain'));
const Handbook = lazy(() => import('./pages/Handbook'));
const Backlog = lazy(() => import('./pages/Backlog'));
const LabRuns = lazy(() => import('./pages/LabRuns'));
const LabForward = lazy(() => import('./pages/LabForward'));
const LabBeta = lazy(() => import('./pages/LabBeta'));
const NewsAccuracy = lazy(() => import('./pages/NewsAccuracy'));
const Profile = lazy(() => import('./pages/Profile'));
const SettingsHome = lazy(() => import('./pages/SettingsHome'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const SAccounts = lazy(() => import('./components/settings/Accounts'));
const SGuardrails = lazy(() => import('./components/journal/GuardrailsSheet'));
const SPortfolio = lazy(() => import('./components/settings/PortfolioReview'));
const SNotifications = lazy(() => import('./components/settings/Notifications'));
const SGoal = lazy(() => import('./components/settings/Goal'));
const SModels = lazy(() => import('./components/settings/AiModel'));
const SAutopilot = lazy(() => import('./components/settings/AutopilotSheet'));
const SEngine = lazy(() => import('./components/paper/EngineSettings'));
const SLab = lazy(() => import('./components/settings/Lab'));
// The five tabs: their chunks are fetched once the first screen is idle, so a tab switch never waits on one.
const TAB_PAGES = [() => import('./pages/Home'), () => import('./pages/Money'), () => import('./pages/Ideas'),
  () => import('./pages/Ai'), () => import('./pages/Market')];
const Home = lazy(TAB_PAGES[0]);
const Money = lazy(TAB_PAGES[1]);
const Ideas = lazy(TAB_PAGES[2]);
const IdeaDetail = lazy(() => import('./pages/IdeaDetail'));
const IdeasHistory = lazy(() => import('./pages/IdeasHistory'));
const Ai = lazy(TAB_PAGES[3]);
const Market = lazy(TAB_PAGES[4]);
const Stock = lazy(() => import('./pages/Stock'));
const WeeklyReport = lazy(() => import('./pages/WeeklyReport'));
const AiStrategy = lazy(() => import('./pages/AiStrategy'));
const AiTrade = lazy(() => import('./pages/AiTrade'));
const RoundTrip = lazy(() => import('./pages/RoundTrip'));
const IndexPage = lazy(() => import('./pages/IndexPage'));
const SectorPage = lazy(() => import('./pages/SectorPage'));
const NewsItem = lazy(() => import('./pages/NewsItem'));
import Login from './pages/Login';
import RequireAuth from './components/RequireAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import ChatWidget from './components/ChatWidget';
import PageHeader from './components/ui/PageHeader';
import Empty from './components/ui/Empty';
import Button from './components/ui/Button';
import { useAuth } from './context/AuthContext';
import { stream } from './lib/ws';
import RequireAdmin from './components/system/RequireAdmin';
import { MOVED, LAB_PAGES, movedTarget, brokerReturnTarget } from './utils/routes.js';

const NotFound = () => (
  <Layout>
    <PageHeader title="Not found" />
    <Empty
      title="No such page"
      body="The address does not match anything here."
      action={<Link to="/"><Button>Back to Home</Button></Link>}
    />
  </Layout>
);

/** A page that moved: same query string, new path. */
const Moved = ({ from, to }) => {
  const { search } = useLocation();
  return <Navigate to={movedTarget(from, to, search)} replace />;
};

/** /mine/stock/:symbol and /research/stock/:symbol are now /stock/:symbol. */
const StockMoved = () => {
  const { symbol } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/stock/${encodeURIComponent(symbol)}${search}`} replace />;
};

const LAB = {
  strategies: <Strategies />, options: <OptionChain />, runs: <LabRuns />,
  forward: <LabForward />, news: <NewsAccuracy />, handbook: <Handbook />, backlog: <Backlog />, beta: <LabBeta />,
};

const App = () => {
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();

  // A broker login that came back to some other page goes on to Accounts, which submits its code.
  useEffect(() => {
    const to = user && brokerReturnTarget(pathname, search);
    if (to) navigate(to, { replace: true });
  }, [user, pathname, search, navigate]);

  // A tapped link opens the next page at its top, not at the scroll offset
  // the last page was left at. Back/forward (POP) keeps the browser's own
  // restoration. Keyed on the path only: a tab or filter change (?tab=,
  // ?book=) stays where the reader is.
  // navigationType is not the trigger: a tab switch is a REPLACE on the same path.
  const scrolledPath = useRef(pathname);
  useEffect(() => {
    if (scrolledPath.current === pathname) return;
    scrolledPath.current = pathname;
    if (navigationType !== 'POP') window.scrollTo(0, 0);
  }, [pathname, navigationType]);

  useEffect(() => {
    if (!user) return undefined;
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1500));
    const id = idle(() => TAB_PAGES.forEach((load) => load().catch(() => {})));
    return () => (window.cancelIdleCallback || clearTimeout)(id);
  }, [user]);

  // One socket for the whole session, opened once signed in and closed on the
  // way out so a logged-out tab never holds an authenticated connection.
  useEffect(() => {
    if (user) {
      stream.connect();
      return () => stream.disconnect();
    }
    return undefined;
  }, [user]);

  // Two boundaries, not one: Layout's own (components/Layout.jsx) catches a
  // crash in what a page renders, keeping the sidebar/nav shell alive so the
  // user can navigate away. This outer one is the fallback for a crash in a
  // page's own hooks/logic, before it ever reaches its `return <Layout>` --
  // Layout never mounts in that case, so the inner boundary can't help.
  const gated = (element) => (
    <RequireAuth>
      <ErrorBoundary>
        <Suspense fallback={null}>{element}</Suspense>
      </ErrorBoundary>
    </RequireAuth>
  );

  return (
    <>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={gated(<Home />)} />
      <Route path="/money" element={gated(<Money />)} />
      <Route path="/ideas" element={gated(<RequireAdmin><Ideas /></RequireAdmin>)} />
      <Route path="/ideas/history" element={gated(<RequireAdmin><IdeasHistory /></RequireAdmin>)} />
      <Route path="/ideas/:id" element={gated(<RequireAdmin><IdeaDetail /></RequireAdmin>)} />
      <Route path="/ai" element={gated(<Ai />)} />
      <Route path="/market" element={gated(<Market />)} />
      <Route path="/stock/:symbol" element={gated(<Stock />)} />
      <Route path="/ai/strategy/:name" element={gated(<AiStrategy />)} />
      <Route path="/ai/trade/:id" element={gated(<AiTrade />)} />
      <Route path="/money/trade/:id" element={gated(<RoundTrip />)} />
      <Route path="/market/index/:ticker" element={gated(<IndexPage />)} />
      <Route path="/market/sector/:name" element={gated(<SectorPage />)} />
      <Route path="/news/:id" element={gated(<NewsItem />)} />
      <Route path="/reports/weekly" element={gated(<WeeklyReport />)} />
      <Route path="/settings" element={gated(<SettingsHome />)} />
      <Route path="/settings/brokers" element={gated(<SettingsPage title="Brokers"><SAccounts /></SettingsPage>)} />
      <Route path="/settings/guardrails" element={gated(<SettingsPage title="Guardrails"><SGuardrails /></SettingsPage>)} />
      <Route path="/settings/portfolio" element={gated(<SettingsPage title="Portfolio review"><SPortfolio isAdmin={user?.role === 'admin'} /></SettingsPage>)} />
      <Route path="/settings/notifications" element={gated(<SettingsPage title="Notifications"><SNotifications /></SettingsPage>)} />
      <Route path="/settings/goal" element={gated(<SettingsPage title="Goal"><SGoal /></SettingsPage>)} />
      <Route path="/settings/ai" element={gated(<SettingsPage title="AI model"><SModels isAdmin={user?.role === 'admin'} /></SettingsPage>)} />
      <Route path="/settings/autopilot" element={gated(<RequireAdmin><SettingsPage title="Autopilot"><SAutopilot /><SEngine /></SettingsPage></RequireAdmin>)} />
      <Route path="/settings/lab" element={gated(<RequireAdmin><SettingsPage title="Lab"><SLab /></SettingsPage></RequireAdmin>)} />
      <Route path="/profile" element={gated(<Profile />)} />
      {/* Lab: frozen and experimental features, admin only, inside Settings */}
      {LAB_PAGES.map((page) => (
        <Route key={page} path={`/settings/lab/${page}`} element={gated(<RequireAdmin>{LAB[page]}</RequireAdmin>)} />
      ))}
      {/* Old links and bookmarks follow the move in one hop, query string included. */}
      <Route path="/mine/stock/:symbol" element={<StockMoved />} />
      <Route path="/research/stock/:symbol" element={<StockMoved />} />
      {MOVED.map(([from, to]) => <Route key={from} path={from} element={<Moved from={from} to={to} />} />)}
      <Route path="*" element={gated(<NotFound />)} />
    </Routes>
    {/* One assistant for the whole signed-in session, so its conversation survives navigation. */}
    {user && <ChatWidget />}
    </>
  );
};

export default App;
