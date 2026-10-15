import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigationType } from 'react-router-dom';
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Strategies = lazy(() => import('./pages/Strategies'));
const OptionChain = lazy(() => import('./pages/OptionChain'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const Journal = lazy(() => import('./pages/Journal'));
const MineOverview = lazy(() => import('./pages/MineOverview'));
const MineHoldings = lazy(() => import('./pages/MineHoldings'));
const MineTax = lazy(() => import('./pages/MineTax'));
const MineStock = lazy(() => import('./pages/MineStock'));
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
  return <Navigate to={['patterns', 'learning'].includes(tab) ? '/mine/journal?tab=habits' : `/mine/journal${search}`} replace />;
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
      {/* Mine: the user's own account -- holdings, ideas for it, trades */}
      <Route path="/mine" element={gated(<MineOverview />)} />
      <Route path="/mine/holdings" element={gated(<MineHoldings />)} />
      <Route path="/mine/tax" element={gated(<MineTax />)} />
      <Route path="/mine/stock/:symbol" element={gated(<MineStock />)} />
      <Route path="/mine/journal" element={gated(<Journal lockedAccount="mine" />)} />
      <Route path="/mine/ideas" element={<Navigate to="/mine" replace />} />
      <Route path="/mine/trades" element={<Navigate to="/mine/journal" replace />} />
      <Route path="/mine/habits" element={<Navigate to="/mine/journal?tab=habits" replace />} />
      {/* AI: the account the app runs, paper until a strategy earns live */}
      <Route path="/ai" element={gated(<AiOverview />)} />
      <Route path="/ai/activity" element={gated(<AiActivity />)} />
      <Route path="/ai/book" element={gated(<Portfolio />)} />
      <Route path="/ai/strategies" element={gated(<Strategies />)} />
      <Route path="/ai/settings" element={gated(<AiLimits />)} />
      {/* Research */}
      <Route path="/research" element={gated(<Dashboard />)} />
      <Route path="/research/stock/:symbol" element={gated(<Dashboard />)} />
      <Route path="/research/news" element={gated(<News />)} />
      <Route path="/research/watchlist" element={gated(<Watchlist />)} />
      {/* Not a tab (Upstox-only, no F&O trading here): reached from the NIFTY / BANK NIFTY cards. */}
      <Route path="/research/options" element={gated(<OptionChain />)} />
      {/* More */}
      <Route path="/settings" element={gated(<Settings />)} />
      <Route path="/profile" element={gated(<Profile />)} />
      <Route path="/system" element={gated(<RequireAdmin><Handbook /></RequireAdmin>)} />
      <Route path="/system/future" element={gated(<RequireAdmin><Backlog /></RequireAdmin>)} />
      {/* Old links and bookmarks follow the move, query string included. */}
      {[
        ['/ai/decisions', '/mine'], ['/ai/autopilot', '/ai/settings'], ['/ai/limits', '/ai/settings'],
        ['/practice', '/ai'], ['/practice/book', '/ai/book'], ['/practice/strategies', '/ai/strategies'],
        ['/practice/setup', '/ai/settings'], ['/practice/decisions', '/mine'], ['/practice/library', '/ai/strategies'],
        ['/ai/practice', '/ai'], ['/ai/practice/decisions', '/mine'], ['/ai/practice/book', '/ai/book'],
        ['/ai/practice/holdings', '/ai/book'], ['/ai/practice/engine', '/ai'], ['/ai/practice/settings', '/ai/settings'],
        ['/decisions', '/mine'], ['/suggestions', '/mine'], ['/paper', '/ai'], ['/paper/decisions', '/mine'],
        ['/paper/holdings', '/ai/book'], ['/paper/engine', '/ai'], ['/paper/settings', '/ai/settings'], ['/trading', '/ai'],
        ['/portfolio', '/mine/holdings'], ['/watchlist', '/research/watchlist'], ['/options', '/research/options'],
        ['/scanner', '/research'], ['/research/scanner', '/research'],
      ].map(([from, to]) => <Route key={from} path={from} element={<Moved to={to} />} />)}
      <Route path="/journal" element={<JournalMoved />} />
      <Route path="*" element={gated(<NotFound />)} />
    </Routes>
  );
};

export default App;
