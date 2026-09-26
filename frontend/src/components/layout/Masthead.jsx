import React from 'react';
import { Link } from 'react-router-dom';
import { Sun, Moon } from 'lucide-react';
import { useStreamStatus } from '../../hooks/useStream';
import { useTheme } from '../../context/useTheme';
import { formatNoteDate, marketPhase } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * The note's masthead. A real contract note is headed by who issued it, under
 * what number, on what date — and this one is live, so it also says whether
 * what you are reading is current.
 */

const FEED = {
  live: { label: 'Live', tone: 'var(--gain)' },
  connecting: { label: 'Connecting', tone: 'var(--ink-faint)' },
  reconnecting: { label: 'Reconnecting', tone: 'var(--stamp)' },
  offline: { label: 'Feed down', tone: 'var(--loss)' },
  idle: { label: 'Idle', tone: 'var(--ink-faint)' },
};

const PHASE = { open: 'Session open', pre: 'Pre-open', closed: 'Market closed' };

export const FeedStatus = ({ className }) => {
  const status = useStreamStatus();
  const feed = FEED[status] || FEED.idle;
  const phase = marketPhase();

  return (
    <span
      className={cn('inline-flex items-center gap-1.5 doc-meta', className)}
      // Screen readers get the whole sentence; sighted readers get the dot.
      aria-label={`${feed.label}. ${PHASE[phase]}.`}
    >
      <span
        aria-hidden="true"
        className="w-1.5 h-1.5 shrink-0"
        style={{ backgroundColor: feed.tone }}
      />
      <span style={{ color: feed.tone }}>{feed.label}</span>
      <span aria-hidden="true" className="text-[var(--rule-strong)]">/</span>
      <span>{PHASE[phase]}</span>
    </span>
  );
};

const Masthead = ({ noteNumber }) => {
  const { theme, toggle } = useTheme();

  return (
    <header
      className="border-b border-[var(--rule-strong)] bg-[var(--paper)]"
      // Installed on a notched phone the page runs under the status bar.
      style={{ paddingTop: 'env(safe-area-inset-top)' }}
    >
      <div className="mx-auto max-w-6xl px-4 lg:px-8">
        <div className="flex items-center justify-between gap-4 py-3">
          <Link to="/" className="min-w-0">
            <h1 className="font-[family-name:var(--font-narrow)] font-bold uppercase tracking-[0.2em] text-sm leading-none">
              Contract Note
            </h1>
            <p className="doc-meta mt-1 truncate">
              NeoTrade · NSE · {formatNoteDate()}
            </p>
          </Link>

          <div className="flex items-center gap-3 shrink-0">
            <span className="doc-meta hidden sm:inline">No. {noteNumber}</span>
            <button
              type="button"
              onClick={toggle}
              className="inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-0 sm:min-w-0 p-1.5 border border-[var(--rule)] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--rule-strong)] transition-colors"
              aria-label={theme === 'dark' ? 'Switch to the original sheet' : 'Switch to the carbon copy'}
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 pb-2">
          <FeedStatus />
          <span className="doc-meta sm:hidden">No. {noteNumber}</span>
        </div>
      </div>
    </header>
  );
};

export default Masthead;
