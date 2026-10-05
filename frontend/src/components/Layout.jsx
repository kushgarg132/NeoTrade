import React, { useEffect, useState } from 'react';
import Sidebar from './layout/Sidebar';
import BottomNav from './layout/BottomNav';
import Masthead from './layout/Masthead';
import ChatWidget from './ChatWidget';
import ErrorBoundary from './ErrorBoundary';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { PendingContext } from '../context/pendingContext';

/** The note's running number: stable per day, the way an issued note is. */
const noteNumber = () => {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const day = Math.floor((now - start) / 86400000);
  return `${now.getFullYear()}/${String(day).padStart(3, '0')}`;
};

/**
 * The shell every page prints inside. The pending count lives here rather than
 * on the suggestions page, because the whole point of the count is to be
 * visible from wherever you are.
 */
const Layout = ({ children }) => {
  const [pending, setPending] = useState(0);

  const loadPending = () =>
    api
      .get(endpoints.suggestions.list({ status: 'PENDING' }))
      .then((res) => setPending(res.data.length))
      .catch(() => setPending(0));
  useEffect(() => {
    loadPending();
  }, []);
  useReconnect(loadPending);

  useTopic('suggestions', (message) => {
    if (message.event === 'created') setPending((count) => count + 1);
    if (message.event === 'decided') setPending((count) => Math.max(0, count - 1));
  });

  return (
    <PendingContext.Provider value={pending}>
    <div className="min-h-screen bg-[var(--paper)] text-[var(--ink)]">
      <Sidebar pendingCount={pending} />

      <div className="lg:pl-56">
        <Masthead noteNumber={noteNumber()} />
        <main className="mx-auto max-w-6xl px-3 sm:px-4 lg:px-8 py-3 sm:py-5 pb-24 lg:pb-12">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>

      <BottomNav pendingCount={pending} />
      <ChatWidget />
    </div>
    </PendingContext.Provider>
  );
};

export default Layout;
