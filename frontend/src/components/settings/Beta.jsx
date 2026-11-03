import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Search } from 'lucide-react';
import { Sheet } from './Panel';
import api, { endpoints } from '../../utils/api';
import { Row } from './Fields';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import { cn } from '../../utils/cn';
import { dayLabel, filterUsers, nextUserSort, sortUsers } from '../../utils/lab';

const BETA_ROWS = [
  ['users', 'Signed up'],
  ['users_with_trades', 'With trades in the journal'],
  ['weekly_active', 'Opened the journal in the last 7 days'],
  ['returned_from_last_week', 'Came back from the week before'],
  ['guardrails_on', 'Guardrails on'],
  ['telegram_linked', 'Telegram linked'],
];

/** Admin only: Phase 12's question — do beta users come back? */
const BetaSheet = () => {
  const [metrics, setMetrics] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => api
    .get(endpoints.journal.betaMetrics)
    .then((res) => { setMetrics(res.data); setFailed(false); })
    .catch(() => setFailed(true));
  useEffect(() => { load(); }, []);

  if (failed) return <Sheet title="Beta" meta="All users"><ErrorLine message="Couldn't load beta metrics." onRetry={load} /></Sheet>;
  if (!metrics) return <Sheet title="Beta" meta="All users"><Skeleton rows={4} /></Sheet>;

  return (
    <Sheet title="Beta" meta="All users">
      {BETA_ROWS.map(([key, label]) => (
        <Row key={key} label={label}>
          <span className="figure-md text-[15px] tabular-nums">
            {metrics[key]}
            {key === 'returned_from_last_week' && ` of ${metrics.active_last_week}`}
          </span>
        </Row>
      ))}
      <Row label="Losing days followed by a journal visit" hint="Within 3 days of the loss.">
        <span className="figure-md text-[15px] tabular-nums">
          {metrics.losing_days_followed_by_open} of {metrics.losing_days}
        </span>
      </Row>
    </Sheet>
  );
};

const USER_SORTS = [['name', 'Name'], ['email', 'Email'], ['created_at', 'Joined'], ['last_open', 'Last opened']];

/** Admin only: who signed up. Filter and sort stay in the browser; all users load at once. */
export const BetaUsers = () => {
  const [users, setUsers] = useState(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' });

  const load = () => api
    .get(endpoints.journal.betaUsers)
    .then((res) => { setUsers(res.data); setFailed(false); })
    .catch(() => setFailed(true));
  useEffect(() => { load(); }, []);

  const rows = useMemo(() => sortUsers(filterUsers(users || [], q), sort), [users, q, sort]);

  if (failed) return <Sheet title="Users"><ErrorLine message="Couldn't load users." onRetry={load} /></Sheet>;
  if (!users) return <Sheet title="Users"><Skeleton rows={4} /></Sheet>;

  return (
    <Sheet title="Users" meta={q.trim() ? `${rows.length} of ${users.length}` : `${users.length} signed up`}>
      <label className="flex items-center gap-2 rounded-[12px] bg-[var(--surface-2)] px-3">
        <Search className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
        <input type="search" aria-label="Filter users" placeholder="Filter by name or email" value={q}
               onChange={(e) => setQ(e.target.value)}
               className="min-h-11 w-full bg-transparent text-[15px] focus:outline-none" />
      </label>
      <div role="group" aria-label="Sort users by" className="mt-2 grid grid-cols-4 border-b border-[var(--border)]">
        {USER_SORTS.map(([id, label]) => {
          const on = sort.key === id;
          const Arrow = sort.dir === 'asc' ? ArrowUp : ArrowDown;
          return (
            <button key={id} type="button" aria-pressed={on} onClick={() => setSort((cur) => nextUserSort(cur, id))}
                    aria-label={`Sort by ${label}${on ? (sort.dir === 'asc' ? ', ascending' : ', descending') : ''}`}
                    className={cn('tap inline-flex min-h-11 items-center justify-center gap-1 text-[13px] font-medium', on ? 'text-[var(--text)]' : 'text-[var(--text-muted)]')}>
              {label}{on && <Arrow className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      {rows.length === 0 && <p className="py-4 text-[14px] text-[var(--text-muted)]">No user matches that.</p>}
      <ul>
        {rows.map((u) => (
          <li key={u.email} className="flex items-start justify-between gap-3 border-b border-[var(--border)] py-3 last:border-b-0">
            <div className="min-w-0">
              <p className="text-[15px] font-medium break-words">{u.name || '–'}</p>
              <p className="text-[13px] text-[var(--text-muted)] break-all">{u.email || '–'}</p>
            </div>
            <div className="shrink-0 text-right text-[13px] tabular-nums text-[var(--text-muted)]">
              <p>Joined {dayLabel(u.created_at)}</p>
              <p>Opened {dayLabel(u.last_open)}</p>
            </div>
          </li>
        ))}
      </ul>
    </Sheet>
  );
};

export default BetaSheet;
