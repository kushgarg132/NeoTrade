import React, { useEffect, useState } from 'react';
import { RefreshCw, Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import SuggestionRecord from '../components/suggestions/SuggestionRecord';
import { Sheet, Empty, Ruling, Tabs } from '../components/doc/Doc';
import WaitingCards from '../components/decisions/WaitingCards';
import AiToday from '../components/decisions/AiToday';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';

/**
 * The decisions inbox, for every account: engine proposals (approve on paper
 * or with real money on the user's own account), cards from the chat or the
 * order ticket that wait for a Confirm, and -- read only -- what the AI
 * account's autopilot did today. Nothing here can trade the AI account.
 *
 *
 * Long-term proposals only: each waits for an explicit approve or decline.
 * Intraday signals execute themselves — nobody can approve a five-minute
 * breakout in time for it to still be one — so they are not listed here.
 */

const ACCOUNTS = [
  { id: 'all', label: 'All' },
  { id: 'paper', label: 'Paper' },
  { id: 'mine', label: 'Mine' },
  { id: 'ai', label: 'AI' },
];

const Decisions = () => {
  const [account, setAccount] = useState('all');
  const [hasMine, setHasMine] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [showDecided, setShowDecided] = useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState(null);

  const load = () => {
    setLoading(true);
    api
      .get(endpoints.suggestions.list({}))
      .then((res) => {
        setItems(res.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load proposals'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  useEffect(() => {
    api
      .get(endpoints.settings.preferences)
      .then((res) => setHasMine(Object.values(res.data.broker_roles || {}).includes('mine')))
      .catch(() => setHasMine(false));
  }, []);

  useReconnect(load);
  useTopic('suggestions', (message) => {
    if (message.event === 'created') {
      setItems((list) => [message.data, ...list]);
    } else {
      setItems((list) =>
        list.map((item) => (item.id === message.data.id ? message.data : item))
      );
    }
  });

  const decide = async (suggestion, kind) => {
    const url = {
      approve: endpoints.suggestions.approve(suggestion.id),
      live: endpoints.suggestions.approveLive(suggestion.id),
      reject: endpoints.suggestions.reject(suggestion.id),
    }[kind];
    const res = await api.post(url, kind === 'reject' ? {} : undefined);
    setItems((list) => list.map((item) => (item.id === suggestion.id ? res.data : item)));
  };

  const scan = async () => {
    setScanning(true);
    setScanNote(null);
    try {
      const res = await api.post(endpoints.suggestions.scan, {});
      setScanNote(
        `Scanning ${res.data.symbols} scrip. New proposals appear here as they are found.`
      );
    } catch (err) {
      setScanNote(err?.response?.data?.detail || 'Could not start the scan');
    } finally {
      setScanning(false);
    }
  };

  // Long-term proposals only: intraday signals execute themselves and their
  // fills are on Practice → Book.
  const inMode = items.filter((item) => item.mode === 'LONGTERM');
  const pending = inMode.filter((item) => item.status === 'PENDING');
  const decided = inMode.filter((item) => item.status !== 'PENDING');
  const visible = showDecided ? decided : pending;

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4">
        <SectionTabs tabs={AI_TABS} label="AI account" />
        <Tabs
          tabs={ACCOUNTS}
          active={account}
          onSelect={setAccount}
          label="Which account"
        />

        {account !== 'ai' && <WaitingCards venue={account === 'all' ? null : account === 'mine' ? 'live' : 'paper'} />}

        {account !== 'ai' && (
        <>
        <Sheet
          title="Proposals"
          meta={`${inMode.filter((i) => i.status === 'PENDING').length} awaiting`}
          actions={
            <Button variant="secondary" size="sm" onClick={scan} disabled={scanning}>
              {scanning ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              <span className="hidden sm:inline">Scan now</span>
              <span className="sm:hidden">Scan</span>
            </Button>
          }
          bodyClassName="p-0"
        >
          <div className="flex items-center justify-between gap-3 px-3 py-2 sm:px-4 sm:py-2.5 bg-[var(--paper-sunk)]">
            <p className="doc-meta normal-case hidden sm:block">
              Long-term proposals wait for your decision.
            </p>
            <button
              type="button"
              onClick={() => setShowDecided((value) => !value)}
              className="field-label text-[var(--stamp)] hover:underline shrink-0 ml-auto min-h-9"
            >
              {showDecided ? `Pending (${pending.length})` : `Decided (${decided.length})`}
            </button>
          </div>

          {scanNote && (
            <p className="px-4 py-2.5 text-sm text-[var(--ink-soft)] border-b border-[var(--rule)]">
              {scanNote}
            </p>
          )}
        </Sheet>

        {loading ? (
          <Sheet>
            <Ruling rows={5} />
          </Sheet>
        ) : error ? (
          <Sheet>
            <Empty
              title="Could not load proposals"
              detail={error}
              action={
                <Button variant="secondary" size="sm" onClick={load}>
                  Retry
                </Button>
              }
            />
          </Sheet>
        ) : visible.length === 0 ? (
          <Sheet>
            <Empty
              title={showDecided ? 'Nothing decided yet' : 'You are clear'}
              detail={
                showDecided
                  ? 'Approved and declined proposals are kept here.'
                  : 'The daily scan runs after the close at 16:00 IST. Run one now if you would rather not wait.'
              }
              action={
                !showDecided ? (
                  <Button variant="secondary" size="sm" onClick={scan} disabled={scanning}>
                    Scan now
                  </Button>
                ) : null
              }
            />
          </Sheet>
        ) : (
          <div className="space-y-2 sm:space-y-3">
            {(showAll ? visible : visible.slice(0, 3)).map((suggestion) => (
              <SuggestionRecord
                key={suggestion.id}
                suggestion={suggestion}
                onApprove={() => decide(suggestion, 'approve')}
                onApproveLive={() => decide(suggestion, 'live')}
                onReject={() => decide(suggestion, 'reject')}
                hasMine={hasMine}
              />
            ))}
            {visible.length > 3 && (
              <button
                type="button"
                onClick={() => setShowAll((value) => !value)}
                aria-expanded={showAll}
                className="w-full sheet py-3 field-label text-[var(--stamp)] hover:bg-[var(--paper-sunk)]"
              >
                {showAll ? 'Show first 3' : `Show ${visible.length - 3} more`}
              </button>
            )}
          </div>
        )}
        </>
        )}

        {(account === 'all' || account === 'ai') && <AiToday />}
      </div>
    </Layout>
  );
};

export default Decisions;
