import React from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { cn } from '../../utils/cn';
import { useAuth } from '../../context/AuthContext';
import { Avatar } from '../common/Avatar';
import { tabsFor, tabActive } from './tabs';

/** Desktop navigation: the bottom tabs as a left rail. */
const SideRail = ({ counts = {} }) => {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  return (
    <aside className="hidden lg:flex fixed left-0 top-0 h-screen w-56 flex-col border-r border-[var(--border)] bg-[var(--surface)] z-30">
      <Link to="/" className="px-5 h-14 flex items-center text-[18px] font-bold text-[var(--text)]">NeoTrade</Link>
      <nav className="flex-1 px-2 py-2 space-y-1" aria-label="Main">
        {tabsFor(user?.role === 'admin').map((item) => {
          const on = tabActive(item, pathname);
          const n = counts[item.counter] || 0;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={cn(
                'tap flex items-center gap-3 px-3 min-h-11 rounded-[12px] text-[15px] font-medium',
                on ? 'bg-[var(--accent-soft)] text-[var(--accent)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)]',
              )}
            >
              <item.icon className="w-5 h-5 shrink-0" aria-hidden="true" />
              <span className="flex-1">{item.label}</span>
              {n > 0 && <span className="min-w-5 px-1 rounded-full bg-[var(--accent)] text-[var(--accent-ink)] text-[12px] leading-5 text-center tabular-nums">{n}</span>}
            </NavLink>
          );
        })}
      </nav>
      <div className="border-t border-[var(--border)] px-4 py-3 flex items-center gap-3">
        <Link to="/profile" className="flex-1 min-w-0 flex items-center gap-2.5" aria-label="Your profile">
          <Avatar src={user?.picture} name={user?.name} size={32} />
          <span className="text-[14px] font-medium truncate text-[var(--text)]">{user?.name || 'Signed in'}</span>
        </Link>
        <button type="button" onClick={logout} className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]" aria-label="Sign out">
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );
};

export default SideRail;
