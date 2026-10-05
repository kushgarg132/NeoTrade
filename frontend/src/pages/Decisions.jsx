import React, { useEffect, useState } from 'react';
import { RefreshCw, Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import SuggestionRecord from '../components/suggestions/SuggestionRecord';
import { Sheet, Empty, Ruling, Tabs } from '../components/doc/Doc';
import WaitingCards from '../components/decisions/WaitingCards';
import AiToday from '../components/decisions/AiToday';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import { cn } from '../utils/cn';

/**
 * The decisions inbox, for every account: engine proposals (approve on paper
 * or with real money on the user's own account), cards from the chat or the
 * order ticket that wait for a Confirm, and -- read only -- what the AI
 * account's autopilot did today. Nothing here can trade the AI account.
 *
 *
 * Long-term proposals wait here for an explicit approve or decline; intraday
 * signals execute themselves — nobody can approve a five-minute breakout in
 * time for it to still be one — so that tab is a record of what fired, not a
 * queue.
 */

const MODES = [
  { id: 'LONGTERM', label: 'Long term' },
  { id: 'INTRADAY', label: 'Intraday' },
];

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
  const [mode, setMode] = useState('LONGTERM');
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

  const inMode = items.filter((item) => item.mode === mode);
  const pending = inMode.filter((item) => item.status === 'PENDING');
  const decided = inMode.filter((item) => item.status !== 'PENDING');
  const visible = showDecided ? decided : pending;

  return (
    <Layout>
      <PaperShell>
      <div className="space-y-3 sm:space-y-4">
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
          meta={`${items.filter((i) => i.status === 'PENDING').length} awaiting`}
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
          <div className="flex border-b border-[var(--rule-strong)]" role="tablist" aria-label="Horizon">
            {MODES.map((item) => {
              const count = items.filter(
                (s) => s.mode === item.id && s.status === 'PENDING'
              ).length;
              const selected = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => {
                    setMode(item.id);
                    setShowDecided(false);
                  }}
                  className={cn(
                    'flex-1 min-h-11 sm:min-h-0 px-3 py-2 sm:px-4 sm:py-3 font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em] border-b-2 -mb-px transition-colors',
                    selected
                      ? 'border-[var(--stamp)] text-[var(--ink)]'
                      : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]'
                  )}
                >
                  {item.label}
                  {count > 0 && (
                    <span className="ml-2 figure-md px-1.5 py-0.5 text-[0.625rem] bg-[var(--stamp)] text-[var(--paper)]">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="flex items-center justify-between gap-3 px-3 py-2 sm:px-4 sm:py-2.5 bg-[var(--paper-sunk)]">
            <p className="doc-meta normal-case hidden sm:block">
              {mode === 'INTRADAY'
                ? 'Intraday signals execute without approval — this is the record.'
                : 'Long-term proposals wait for your decision.'}
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
                  : mode === 'LONGTERM'
                    ? 'The daily scan runs after the close at 16:00 IST. Run one now if you would rather not wait.'
                    : 'Intraday signals appear here once an engine run fires one.'
              }
              action={
                !showDecided && mode === 'LONGTERM' ? (
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
      </PaperShell>
    </Layout>
  );
};

export default Decisions;
