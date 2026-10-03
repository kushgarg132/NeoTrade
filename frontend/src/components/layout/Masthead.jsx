import React from 'react';
import { Link } from 'react-router-dom';
import { Sun, Moon, MessageSquare } from 'lucide-react';
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
const PHASE_SHORT = { open: 'Open', pre: 'Pre-open', closed: 'Closed' };

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
      <span className="sm:hidden">{PHASE_SHORT[phase]}</span>
      <span className="hidden sm:inline">{PHASE[phase]}</span>
    </span>
  );
};

/** Opens the margin note (ChatWidget) from the masthead on a phone. */
const toggleMarginNote = () => window.dispatchEvent(new Event('margin-note:toggle'));

const ICON_BUTTON =
  'inline-flex items-center justify-center min-h-11 min-w-11 lg:min-h-8 lg:min-w-8 border border-[var(--rule)] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--rule-strong)] transition-colors';

/**
 * One printed line on a phone: who issued the note, whether it is live, and
 * the two tools every page needs. The note number and date stay on wider
 * sheets, where there is room for furniture.
 */
const Masthead = ({ noteNumber }) => {
  const { theme, toggle } = useTheme();

  return (
    <header
      className="sticky top-0 z-40 border-b border-[var(--rule-strong)] bg-[var(--paper)]"
      // Installed on a notched phone the page runs under the status bar.
      style={{ paddingTop: 'env(safe-area-inset-top)' }}
    >
      <div className="mx-auto max-w-6xl px-3 sm:px-4 lg:px-8 h-[var(--masthead-h)] flex items-center justify-between gap-3">
        <Link to="/" className="min-w-0 flex items-baseline gap-3">
          <h1 className="font-[family-name:var(--font-narrow)] font-bold uppercase tracking-[0.2em] text-sm leading-none whitespace-nowrap">
            Contract Note
          </h1>
          <span className="doc-meta hidden md:inline truncate">
            NeoTrade · NSE · {formatNoteDate()} · No. {noteNumber}
          </span>
        </Link>

        <div className="flex items-center gap-2 shrink-0">
          <FeedStatus className="mr-1" />
          <button type="button" onClick={toggleMarginNote} className={cn(ICON_BUTTON, 'lg:hidden')} aria-label="Open the margin note">
            <MessageSquare className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={toggle}
            className={ICON_BUTTON}
            aria-label={theme === 'dark' ? 'Switch to the original sheet' : 'Switch to the carbon copy'}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </header>
  );
};

export default Masthead;
