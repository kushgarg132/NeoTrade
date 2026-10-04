import React, { useEffect, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';

const KEY = 'neotrade_account';
const read = () => {
  try {
    return localStorage.getItem(KEY) || 'all';
  } catch {
    return 'all';
  }
};

/** Which account a page shows: both, the AI's, or the user's own
    (backend/brokers/roles.py). Remembered per viewer; hidden until roles are set. */
export const useAccount = () => {
  const [account, setAccountState] = useState(read);
  const [roles, setRoles] = useState(null);
  useEffect(() => {
    api.get(endpoints.settings.preferences).then((res) => setRoles(res.data.broker_roles || {})).catch(() => setRoles({}));
  }, []);
  const setAccount = (value) => {
    setAccountState(value);
    try {
      localStorage.setItem(KEY, value);
    } catch {
      /* private mode: not remembered */
    }
  };
  const hasBoth = roles && Object.values(roles).includes('ai') && Object.values(roles).includes('mine');
  return { account: hasBoth ? account : 'all', setAccount, roles, hasBoth };
};

const name = (roles, role) => {
  const broker = Object.keys(roles || {}).find((b) => roles[b] === role);
  return broker ? broker.charAt(0).toUpperCase() + broker.slice(1) : '';
};

export const AccountSwitch = ({ account, setAccount, roles, hasBoth }) => {
  if (!hasBoth) return null;
  const options = [['all', 'Both'], ['ai', `AI · ${name(roles, 'ai')}`], ['mine', `Mine · ${name(roles, 'mine')}`]];
  return (
    <div role="radiogroup" aria-label="Account" className="flex gap-1.5">
      {options.map(([value, label]) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={account === value}
          onClick={() => setAccount(value)}
          className={cn(
            'h-11 sm:h-8 px-3 text-xs border transition-colors',
            account === value
              ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
              : 'border-[var(--rule-strong)] text-[var(--ink-soft)] hover:border-[var(--ink)]',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
};
