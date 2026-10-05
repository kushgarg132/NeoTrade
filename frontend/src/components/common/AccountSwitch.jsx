import React from 'react';
import { cn } from '../../utils/cn';

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
