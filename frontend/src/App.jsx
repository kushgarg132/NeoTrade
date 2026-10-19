import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigationType, useParams } from 'react-router-dom';
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
const Import = lazy(() => import('./pages/Import'));
const News = lazy(() => import('./pages/News'));
const AiOverview = lazy(() => import('./pages/AiOverview'));
const AiActivity = lazy(() => import('./pages/AiActivity'));
import Login from './pages/Login';
const Handbook = lazy(() => import('./pages/Handbook'));
const Backlog = lazy(() => import('./pages/Backlog'));
const Picks = lazy(() => import('./pages/Picks'));
import RequireAuth from './components/RequireAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { Sheet, Empty } from './components/doc/Doc';
import { useAuth } from './context/AuthContext';
import { stream } from './lib/ws';
import RequireAdmin from './components/system/RequireAdmin';
import { MOVED } from './utils/routes.js';

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

/** /journal?tab=patterns|learning now lives under the Habits tab. */
const JournalRoute = () => {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (['patterns', 'learning'].includes(params.get('tab'))) {
    return <Navigate to="/journal?tab=habits" replace />;
  }
  return <Journal lockedAccount="mine" />;
};

/** /mine/stock/:symbol and /research/stock/:symbol are now /stock/:symbol. */
const StockMoved = () => {
  const { symbol } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/stock/${encodeURIComponent(symbol)}${search}`} replace />;
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
      {/* Portfolio: the user's own account -- holdings, tax, news, watchlist */}
      <Route path="/portfolio" element={gated(<MineOverview />)} />
      <Route path="/portfolio/holdings" element={gated(<MineHoldings />)} />
      <Route path="/portfolio/tax" element={gated(<MineTax />)} />
      <Route path="/portfolio/news" element={gated(<News />)} />
      <Route path="/portfolio/watchlist" element={gated(<Watchlist />)} />
      <Route path="/portfolio/import" element={gated(<Import />)} />
      {/* One stock page: position (when held) plus the analysis */}
      <Route path="/stock/:symbol" element={gated(<MineStock />)} />
      {/* Journal: trades, habits, guardrails (?tab=) */}
      <Route path="/journal" element={gated(<JournalRoute />)} />
      {/* Picks: admin only until the SEBI RA registration exists */}
      <Route path="/picks" element={gated(<RequireAdmin><Picks /></RequireAdmin>)} />
      {/* AI: the account the app runs, paper until a strategy earns live */}
      <Route path="/ai" element={gated(<AiOverview />)} />
      <Route path="/ai/activity" element={gated(<AiActivity />)} />
      <Route path="/ai/book" element={gated(<Portfolio />)} />
      {/* Lab: frozen and experimental features, admin only */}
      <Route path="/lab" element={gated(<RequireAdmin><Strategies /></RequireAdmin>)} />
      <Route path="/lab/limits" element={gated(<RequireAdmin><AiLimits /></RequireAdmin>)} />
      <Route path="/lab/options" element={gated(<RequireAdmin><OptionChain /></RequireAdmin>)} />
      <Route path="/lab/handbook" element={gated(<RequireAdmin><Handbook /></RequireAdmin>)} />
      <Route path="/lab/backlog" element={gated(<RequireAdmin><Backlog /></RequireAdmin>)} />
      {/* Setup */}
      <Route path="/settings" element={gated(<Settings />)} />
      <Route path="/profile" element={gated(<Profile />)} />
      {/* Old links and bookmarks follow the move in one hop, query string included. */}
      <Route path="/mine/stock/:symbol" element={<StockMoved />} />
      <Route path="/research/stock/:symbol" element={<StockMoved />} />
      {MOVED.map(([from, to]) => <Route key={from} path={from} element={<Moved to={to} />} />)}
      <Route path="*" element={gated(<NotFound />)} />
    </Routes>
  );
};

export default App;
