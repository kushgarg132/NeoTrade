import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigationType } from 'react-router-dom';
const Dashboard = lazy(() => import('./pages/Dashboard'));
const PaperOverview = lazy(() => import('./pages/PaperOverview'));
const PaperSettings = lazy(() => import('./pages/PaperSettings'));
const Strategies = lazy(() => import('./pages/Strategies'));
const OptionChain = lazy(() => import('./pages/OptionChain'));
const Decisions = lazy(() => import('./pages/Decisions'));
const ScannerPage = lazy(() => import('./pages/ScannerPage'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const Journal = lazy(() => import('./pages/Journal'));
const MyPortfolio = lazy(() => import('./pages/MyPortfolio'));
const Settings = lazy(() => import('./pages/Settings'));
const Profile = lazy(() => import('./pages/Profile'));
const AiLimits = lazy(() => import('./pages/AiLimits'));
const Today = lazy(() => import('./pages/Today'));
const News = lazy(() => import('./pages/News'));
const AiOverview = lazy(() => import('./pages/AiOverview'));
const AiActivity = lazy(() => import('./pages/AiActivity'));
import Login from './pages/Login';
const Handbook = lazy(() => import('./pages/Handbook'));
const Backlog = lazy(() => import('./pages/Backlog'));
import RequireAuth from './components/RequireAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { Sheet, Empty } from './components/doc/Doc';
import { useAuth } from './context/AuthContext';
import { stream } from './lib/ws';
import RequireAdmin from './components/system/RequireAdmin';

const NotFound = () => (
  <Layout>
    <Sheet title="Not found">
      <Empty
        title="No such section of the note"
        detail="The address does not match any part of this statement."
        action={
          <Link to="/" className="field-label text-[var(--stamp)] hover:underline">
            Back to the statement
          </Link>
        }
      />
    </Sheet>
  </Layout>
);

/** A page that moved: same query string, new path. */
const Moved = ({ to }) => {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
};

/** /journal?tab=patterns|learning now lives under Mine → Habits. */
const JournalMoved = () => {
  const { search } = useLocation();
  const tab = new URLSearchParams(search).get('tab');
  return <Navigate to={`${['patterns', 'learning'].includes(tab) ? '/mine/habits' : '/mine/trades'}${search}`} replace />;
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
      {/* Today */}
      <Route path="/" element={gated(<Today />)} />
      {/* Mine: the user's own account */}
      <Route path="/mine" element={<Navigate to="/mine/holdings" replace />} />
      <Route path="/mine/holdings" element={gated(<MyPortfolio lockedAccount="mine" />)} />
      <Route path="/mine/trades" element={gated(<Journal view="trades" lockedAccount="mine" />)} />
      <Route path="/mine/habits" element={gated(<Journal view="habits" lockedAccount="mine" />)} />
      {/* AI: the AI account and its autopilot only */}
      <Route path="/ai" element={gated(<AiOverview />)} />
      <Route path="/ai/activity" element={gated(<AiActivity />)} />
      <Route path="/ai/autopilot" element={gated(<AiLimits />)} />
      {/* Research */}
      <Route path="/research" element={gated(<Dashboard />)} />
      <Route path="/research/stock/:symbol" element={gated(<Dashboard />)} />
      <Route path="/research/news" element={gated(<News />)} />
      <Route path="/research/watchlist" element={gated(<Watchlist />)} />
      <Route path="/research/scanner" element={gated(<ScannerPage />)} />
      <Route path="/research/options" element={gated(<OptionChain />)} />
      {/* More */}
      <Route path="/settings" element={gated(<Settings />)} />
      <Route path="/profile" element={gated(<Profile />)} />
      <Route path="/system" element={gated(<RequireAdmin><Handbook /></RequireAdmin>)} />
      <Route path="/system/future" element={gated(<RequireAdmin><Backlog /></RequireAdmin>)} />
      {/* Practice (under More): the strategy engine, its decisions and its book */}
      <Route path="/practice" element={gated(<PaperOverview />)} />
      <Route path="/practice/decisions" element={<Moved to="/ai/decisions" />} />
      <Route path="/practice/book" element={gated(<Portfolio />)} />
      <Route path="/practice/setup" element={gated(<PaperSettings />)} />
      <Route path="/practice/strategies" element={gated(<Strategies />)} />
      <Route path="/practice/library" element={<Moved to="/practice/strategies" />} />
      {/* Old links and bookmarks follow the move, query string included. */}
      <Route path="/portfolio" element={<Moved to="/mine/holdings" />} />
      <Route path="/journal" element={<JournalMoved />} />
      <Route path="/watchlist" element={<Moved to="/research/watchlist" />} />
      <Route path="/scanner" element={<Moved to="/research/scanner" />} />
      <Route path="/options" element={<Moved to="/research/options" />} />
      <Route path="/ai/limits" element={<Moved to="/ai/autopilot" />} />
      <Route path="/ai/practice" element={<Moved to="/practice" />} />
      <Route path="/ai/decisions" element={gated(<Decisions />)} />
      <Route path="/ai/practice/decisions" element={<Moved to="/ai/decisions" />} />
      <Route path="/ai/practice/book" element={<Moved to="/practice/book" />} />
      <Route path="/ai/practice/holdings" element={<Moved to="/practice/book" />} />
      <Route path="/ai/practice/engine" element={<Moved to="/practice" />} />
      <Route path="/ai/practice/settings" element={<Moved to="/practice/setup" />} />
      <Route path="/decisions" element={<Moved to="/ai/decisions" />} />
      <Route path="/paper" element={<Moved to="/practice" />} />
      <Route path="/paper/decisions" element={<Moved to="/ai/decisions" />} />
      <Route path="/paper/holdings" element={<Moved to="/practice/book" />} />
      <Route path="/paper/engine" element={<Moved to="/practice" />} />
      <Route path="/paper/settings" element={<Moved to="/practice/setup" />} />
      <Route path="/suggestions" element={<Moved to="/ai/decisions" />} />
      <Route path="/trading" element={<Moved to="/practice" />} />
      <Route path="*" element={gated(<NotFound />)} />
    </Routes>
  );
};

export default App;
