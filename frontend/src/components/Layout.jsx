import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import SideRail from './layout/SideRail';
import BottomTabs from './layout/BottomTabs';
import Header from './layout/Header';
import ChatWidget from './ChatWidget';
import ErrorBoundary from './ErrorBoundary';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { PendingContext } from '../context/pendingContext';

/**
 * The shell every page prints inside. The pending count lives here rather than
 * on the suggestions page, because the whole point of the count is to be
 * visible from wherever you are.
 */
const Layout = ({ children }) => {
  const [pending, setPending] = useState(0);

  const loadPending = () =>
    api
      .get(endpoints.mine.actions)
      .then((res) => setPending(res.data.length))
      .catch(() => setPending(0));
  useEffect(() => {
    loadPending();
  }, []);
  useReconnect(loadPending);

  // Counts Mine's Needs-you list. Re-counted on each suggestion event, since
  // ideas are part of it and a failed send can put one back to PENDING.
  // The nav badge: what needs the user outside practice (GET /today/attention).
  const [attention, setAttention] = useState(0);
  const loadAttention = () =>
    api.get(endpoints.todayAttention).then((res) => setAttention(res.data.count)).catch(() => setAttention(0));
  useEffect(() => {
    loadAttention();
  }, []);
  useReconnect(loadAttention);

  useTopic('suggestions', () => {
    loadPending();
    loadAttention(); // an interrupted approval lands as NEEDS_REVIEW
  });

  // Material news on something the user holds (backend/datalayer/reactor.py):
  // a toast for a while, wherever they are. The News page keeps the full list.
  const [alerts, setAlerts] = useState([]);
  const dismiss = (id) => setAlerts((list) => list.filter((a) => a.id !== id));
  useTopic('news', (message) => {
    const alert = message.data;
    if (!alert?.id) return;
    setAlerts((list) => [alert, ...list.filter((a) => a.id !== alert.id)].slice(0, 3));
    setTimeout(() => dismiss(alert.id), 15_000);
  });

  const counts = { attention, pending };

  return (
    <PendingContext.Provider value={pending}>
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <SideRail counts={counts} />

      <div className="lg:pl-56">
        <Header />
        <main className="mx-auto max-w-5xl px-4 py-4 pb-24 lg:pb-12">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>

      <div role="status" aria-live="polite" className="fixed z-50 right-3 bottom-20 lg:bottom-4 w-[min(22rem,calc(100vw-1.5rem))] space-y-2">
        {alerts.map((alert) => (
          <div key={alert.id} className="sheet px-3 py-2.5 shadow-lg flex gap-2 items-start bg-[var(--surface)]">
            <Link to="/market?tab=news" onClick={() => dismiss(alert.id)} className="flex-1 min-w-0 text-sm hover:text-[var(--accent)]">
              <span className="block font-semibold">{alert.event || alert.title}</span>
              <span className="block doc-meta normal-case">
                {(alert.hits || []).map((h) => `${h.target === 'INDIA' ? 'Market' : h.target} ${h.direction > 0 ? '↑' : '↓'} ${h.impact}/10`).join(' · ')}
              </span>
            </Link>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(alert.id)} className="min-h-9 min-w-9 inline-flex items-center justify-center text-[var(--text-muted)]">
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <BottomTabs counts={counts} />
      <ChatWidget />
    </div>
    </PendingContext.Provider>
  );
};

export default Layout;
