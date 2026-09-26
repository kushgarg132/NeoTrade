import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Link, Navigate } from 'react-router-dom';
const Dashboard = lazy(() => import('./pages/Dashboard'));
const PaperOverview = lazy(() => import('./pages/PaperOverview'));
const PaperSettings = lazy(() => import('./pages/PaperSettings'));
const Suggestions = lazy(() => import('./pages/Suggestions'));
const ScannerPage = lazy(() => import('./pages/ScannerPage'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const Journal = lazy(() => import('./pages/Journal'));
const Trading = lazy(() => import('./pages/Trading'));
const Settings = lazy(() => import('./pages/Settings'));
import Login from './pages/Login';
const SystemArchitecturePage = lazy(() => import('./pages/SystemArchitecturePage'));
import RequireAuth from './components/RequireAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { Sheet, Empty } from './components/doc/Doc';
import { useAuth } from './context/AuthContext';
import { stream } from './lib/ws';

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

const App = () => {
  const { user } = useAuth();

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
      <Route path="/" element={gated(<Dashboard />)} />
      <Route path="/paper" element={gated(<PaperOverview />)} />
      <Route path="/paper/decisions" element={gated(<Suggestions />)} />
      <Route path="/paper/holdings" element={gated(<Portfolio />)} />
      <Route path="/paper/engine" element={gated(<Trading />)} />
      <Route path="/paper/settings" element={gated(<PaperSettings />)} />
      {/* The engine's pages moved under /paper; old links and bookmarks follow. */}
      <Route path="/suggestions" element={<Navigate to="/paper/decisions" replace />} />
      <Route path="/portfolio" element={<Navigate to="/paper/holdings" replace />} />
      <Route path="/trading" element={<Navigate to="/paper/engine" replace />} />
      <Route path="/scanner" element={gated(<ScannerPage />)} />
      <Route path="/watchlist" element={gated(<Watchlist />)} />
      <Route path="/journal" element={gated(<Journal />)} />
      <Route path="/settings" element={gated(<Settings />)} />
      <Route path="/system" element={gated(<SystemArchitecturePage />)} />
      <Route path="*" element={gated(<NotFound />)} />
    </Routes>
  );
};

export default App;
