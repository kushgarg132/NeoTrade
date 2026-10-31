import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sun, Moon, MessageSquare, Eye, EyeOff, Search, User } from 'lucide-react';
import SmartSearch from '../dashboard/SmartSearch';
import { stockPath } from '../../utils/stocks';
import { usePrivacy, togglePrivacy } from '../../hooks/usePrivacy';
import { useStreamStatus } from '../../hooks/useStream';
import { useTheme } from '../../context/useTheme';
import { marketPhase } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import Logo from './Logo';

const PHASE = { open: 'Market open', pre: 'Pre-open', closed: 'Market closed' };
// Phones get a word too: the dot's colour never carries the state alone.
const SHORT = { open: 'Open', pre: 'Pre-open', closed: 'Closed' };
const BTN = 'tap inline-flex items-center justify-center min-h-11 min-w-11 rounded-[12px] text-[var(--text-muted)]';

/** The dot is the live socket: green while connected, amber otherwise (red is kept for money). The word is the market phase, or "Offline"/"Stale" on phones when the feed is down. */
const MarketDot = () => {
  const feed = useStreamStatus();
  const phase = marketPhase();
  const color = feed === 'live' ? 'var(--gain)' : 'var(--warn)';
  return (
    <span role="img" aria-label={`${PHASE[phase]}. Feed ${feed}.`} className="inline-flex items-center gap-1.5 px-1 text-[12px] text-[var(--text-muted)]">
      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
      <span className="sm:hidden">{feed === 'offline' ? 'Offline' : feed === 'reconnecting' ? 'Stale' : SHORT[phase]}</span>
      <span className="hidden sm:inline">{PHASE[phase]}</span>
    </span>
  );
};

/** Every screen: logo, stock search, market dot, privacy, theme, profile/settings. */
const Header = () => {
  const { theme, toggle } = useTheme();
  const hidden = usePrivacy();
  const navigate = useNavigate();
  const [searching, setSearching] = useState(false);
  const openStock = (symbol) => {
    setSearching(false);
    navigate(stockPath(symbol));
  };
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]" style={{ paddingTop: 'env(safe-area-inset-top)' }}>
      <div className="mx-auto max-w-5xl px-4 h-14 flex items-center justify-between gap-2">
        <Link to="/" className="lg:hidden shrink-0" aria-label="NeoTrade home"><Logo /></Link>
        <SmartSearch compact className="hidden sm:block w-full max-w-xs lg:max-w-sm" onSearch={openStock} />
        <div className="flex items-center gap-0.5 shrink-0 ml-auto">
          <button type="button" onClick={() => setSearching((v) => !v)} className={cn(BTN, 'sm:hidden', searching && 'text-[var(--accent)]')} aria-expanded={searching} aria-label="Find a stock">
            <Search className="w-5 h-5" />
          </button>
          <MarketDot />
          <button type="button" onClick={() => window.dispatchEvent(new Event('margin-note:toggle'))} className={cn(BTN, 'lg:hidden')} aria-label="Open the assistant">
            <MessageSquare className="w-5 h-5" />
          </button>
          <button type="button" onClick={togglePrivacy} className={cn(BTN, hidden && 'text-[var(--accent)]')} aria-pressed={hidden} aria-label={hidden ? 'Show amounts' : 'Hide amounts'}>
            {hidden ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
          </button>
          {/* Phones: theme lives in Settings, freeing room for the market word. */}
          <button type="button" onClick={toggle} className={cn(BTN, 'hidden sm:inline-flex')} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          </button>
          <Link to="/settings" className={BTN} aria-label="Profile and settings">
            <User className="w-5 h-5" />
          </Link>
        </div>
      </div>
      {searching && (
        <div className="sm:hidden border-t border-[var(--border)] px-4 py-2">
          <SmartSearch compact autoFocus onSearch={openStock} />
        </div>
      )}
    </header>
  );
};

export default Header;
