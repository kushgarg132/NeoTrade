import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { X } from 'lucide-react';
import SideRail from './layout/SideRail';
import BottomTabs from './layout/BottomTabs';
import { sectionOf } from './layout/tabs';
import Header from './layout/Header';
import StatusStrip from './layout/StatusStrip';
import ErrorBoundary from './ErrorBoundary';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { useNeedCount } from '../hooks/useNeedCount';
import { loadNewsTrust, useNewsTrust } from '../hooks/useNewsTrust';
import { lean } from '../utils/newsTrust';
import { useAuth } from '../context/AuthContext';
import { alerts as statusAlerts } from '../utils/home';

/**
 * The shell every page prints inside. The pending count lives here rather than
 * on the suggestions page, because the whole point of the count is to be
 * visible from wherever you are.
 */
// Each page mounts its own Layout: the last answer seeds the next page, so the strip does not blink on navigation.
let lastAttention = null;

const Layout = ({ children }) => {
  const { user } = useAuth();
  const pending = useNeedCount().count; // the one "needs you" number, shared with Home
  useNewsTrust();
  useEffect(() => { loadNewsTrust(); }, []);

  // Each section's colour (index.css `[data-section]`), on <html> so the theme class and it meet.
  const { pathname } = useLocation();
  const section = sectionOf(pathname);
  useEffect(() => {
    document.documentElement.dataset.section = section;
    return () => { delete document.documentElement.dataset.section; }; // Login and the rest: the base accent
  }, [section]);

  // The nav badge and the status strip: what needs the user outside practice, and the kill switch,
  // live-armed and broker-login facts, on every page (GET /today/attention).
  const [attention, setAttention] = useState(() => lastAttention);
  // Guests have no account (and no socket): no badge, no strip, no personal topics.
  const loadAttention = () => {
    if (!user) return undefined;
    // A failed read keeps the last strip: a vanished kill-switch line would read as "all clear".
    return api.get(endpoints.todayAttention).then((res) => setAttention((lastAttention = res.data))).catch(() => {});
  };
  useEffect(() => {
    loadAttention();
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps
  useReconnect(loadAttention);

  useTopic(user ? 'suggestions' : null, () => {
    loadAttention(); // an interrupted approval lands as NEEDS_REVIEW
  });
  useTopic(user ? 'autopilot' : null, () => loadAttention()); // Stop AI clears the live-armed line
  useTopic(user ? 'guardrails' : null, () => loadAttention()); // the kill switch trips

  // Material news on something the user holds (backend/datalayer/reactor.py):
  // a toast for a while, wherever they are, just under the header. The News page keeps the full list.
  const [alerts, setAlerts] = useState([]);
  const dismiss = (id) => setAlerts((list) => list.filter((a) => a.id !== id));
  useTopic(user ? 'news' : null, (message) => {
    const alert = message.data;
    if (!alert?.id) return;
    setAlerts((list) => [alert, ...list.filter((a) => a.id !== alert.id)].slice(0, 3));
    setTimeout(() => dismiss(alert.id), 15_000);
  });

  const counts = { attention: user ? attention?.count || 0 : 0, pending };

  return (
    <>
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <SideRail counts={counts} />

      <div className="lg:pl-56">
        <Header />
        {/* Kill switch and live armed show on every page; an expired broker login only on Today (owner, 2026-11-27). */}
        {user && attention && <StatusStrip items={statusAlerts(attention).filter((a) => !a.login || pathname === '/')} />}
        <main className="mx-auto max-w-5xl px-4 py-4 pb-24 lg:pb-12">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>

      <div role="status" aria-live="polite" className="fixed z-50 right-3 top-[calc(env(safe-area-inset-top)+4rem)] w-[min(22rem,calc(100vw-1.5rem))] space-y-2">
        {alerts.map((alert) => (
          <div key={alert.id} className="rounded-[12px] border border-[var(--border)] px-3 py-2.5 flex gap-2 items-start bg-[var(--surface)]">
            <Link to="/market?tab=news" onClick={() => dismiss(alert.id)} className="flex-1 min-w-0 text-sm hover:text-[var(--accent)]">
              <span className="block font-semibold">{alert.event || alert.title}</span>
              <span className="block text-[13px] text-[var(--text-muted)]">
                {(alert.hits || []).map((h) => `${h.target === 'INDIA' ? 'Market' : h.target} ${['↓', '·', '↑'][lean(h.direction) + 1]} ${h.impact}/10`).join(' · ')}
              </span>
            </Link>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(alert.id)} className="min-h-9 min-w-9 inline-flex items-center justify-center text-[var(--text-muted)]">
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <BottomTabs counts={counts} />
    </div>
    </>
  );
};

export default Layout;
