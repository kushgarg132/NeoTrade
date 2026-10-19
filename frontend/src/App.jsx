import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigationType, useParams } from 'react-router-dom';
const Strategies = lazy(() => import('./pages/Strategies'));
const OptionChain = lazy(() => import('./pages/OptionChain'));
const Handbook = lazy(() => import('./pages/Handbook'));
const Backlog = lazy(() => import('./pages/Backlog'));
const LabRuns = lazy(() => import('./pages/LabRuns'));
const LabForward = lazy(() => import('./pages/LabForward'));
const Profile = lazy(() => import('./pages/Profile'));
const SettingsHome = lazy(() => import('./pages/SettingsHome'));
const Home = lazy(() => import('./pages/Home'));
const Money = lazy(() => import('./pages/Money'));
const Ideas = lazy(() => import('./pages/Ideas'));
const IdeaDetail = lazy(() => import('./pages/IdeaDetail'));
const IdeasHistory = lazy(() => import('./pages/IdeasHistory'));
const Ai = lazy(() => import('./pages/Ai'));
const Market = lazy(() => import('./pages/Market'));
const Stock = lazy(() => import('./pages/Stock'));
const WeeklyReport = lazy(() => import('./pages/WeeklyReport'));
import Login from './pages/Login';
import RequireAuth from './components/RequireAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import PageHeader from './components/ui/PageHeader';
import Empty from './components/ui/Empty';
import Button from './components/ui/Button';
import { useAuth } from './context/AuthContext';
import { stream } from './lib/ws';
import RequireAdmin from './components/system/RequireAdmin';
import { MOVED, LAB_PAGES, movedTarget } from './utils/routes.js';

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
  forward: <LabForward />, handbook: <Handbook />, backlog: <Backlog />,
};

const App = () => {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const navigationType = useNavigationType();

  // A tapped link opens the next page at its top, not at the scroll offset
  // the last page was left at. Back/forward (POP) keeps the browser's own
  // restoration. Keyed on the path only: a tab or filter change (?tab=,
  // ?book=) stays where the reader is.
  useEffect(() => {
    if (navigationType !== 'POP') window.scrollTo(0, 0);
  }, [pathname, navigationType]);

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
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={gated(<Home />)} />
      <Route path="/money" element={gated(<Money />)} />
      <Route path="/ideas" element={gated(<Ideas />)} />
      <Route path="/ideas/history" element={gated(<IdeasHistory />)} />
      <Route path="/ideas/:id" element={gated(<IdeaDetail />)} />
      <Route path="/ai" element={gated(<Ai />)} />
      <Route path="/market" element={gated(<Market />)} />
      <Route path="/stock/:symbol" element={gated(<Stock />)} />
      <Route path="/reports/weekly" element={gated(<WeeklyReport />)} />
      <Route path="/settings" element={gated(<SettingsHome />)} />
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
  );
};

export default App;
