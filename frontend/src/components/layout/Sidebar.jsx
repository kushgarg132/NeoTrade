import React from 'react';
import { Link, NavLink } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { cn } from '../../utils/cn';
import { useAuth } from '../../context/AuthContext';
import { SECTIONS } from './sections';
import { Avatar } from '../common/Avatar';

const Sidebar = ({ pendingCount = 0 }) => {
  const { user, logout } = useAuth();

  return (
    <aside className="hidden lg:flex fixed left-0 top-0 h-screen w-56 flex-col border-r border-[var(--rule-strong)] bg-[var(--paper-sunk)] z-30">
      <div className="px-5 py-4 border-b border-[var(--rule-strong)]">
        <p className="font-[family-name:var(--font-narrow)] font-bold uppercase tracking-[0.2em] text-xs leading-none">
          Contract Note
        </p>
        <p className="doc-meta mt-1.5">NeoTrade</p>
      </div>

      <nav className="flex-1 py-2 overflow-y-auto" aria-label="Sections">
        {SECTIONS.map((item) => (
          <React.Fragment key={item.path}>
          {/* The tear between the real-money pages and the practice book. */}
          {item.divider && <div className="perforated mx-5 my-2" aria-hidden="true" />}
          <NavLink
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-5 py-2.5 border-l-2 transition-colors',
                'font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em]',
                isActive
                  ? 'border-[var(--stamp)] text-[var(--ink)] bg-[var(--paper)]'
                  : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)] hover:bg-[var(--paper)]'
              )
            }
          >
            <item.icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
            <span className="flex-1">{item.label}</span>
            {item.counter && pendingCount > 0 && (
              <span className="figure-md text-[0.6875rem] px-1.5 py-0.5 bg-[var(--stamp)] text-[var(--paper)]">
                {pendingCount}
              </span>
            )}
          </NavLink>
          </React.Fragment>
        ))}
      </nav>

      <div className="border-t border-[var(--rule-strong)] px-5 py-3 flex items-center gap-3">
        <Link to="/profile" className="flex-1 min-w-0 flex items-center gap-2.5 group" aria-label="Your profile">
          <Avatar src={user?.picture} name={user?.name} size={32} />
          <div className="min-w-0">
            <p className="text-xs font-semibold truncate group-hover:text-[var(--stamp)]">{user?.name || 'Signed in'}</p>
            <p className="doc-meta truncate normal-case">{user?.email}</p>
          </div>
        </Link>
        <button
          type="button"
          onClick={logout}
          className="p-1.5 text-[var(--ink-faint)] hover:text-[var(--loss)] transition-colors"
          aria-label="Sign out"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
