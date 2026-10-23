import React from 'react';
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toneText } from './tone';

/**
 * A home-screen tile: label, one headline figure, a sub-line, and an optional `meta` line
 * (freshness, from formatters.asOf: `{ text, stale }`). A tile with `to` is one tap.
 */
const Tile = ({ title, value, sub, tone = 'neutral', subTone = 'neutral', meta, to, icon: Icon }) => {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)]">
        {Icon && <Icon className="w-4 h-4" aria-hidden="true" />}
        <span className="flex-1">{title}</span>
        {to && <ChevronRight className="w-4 h-4 shrink-0" aria-hidden="true" />}
      </div>
      <div className={`private mt-1 text-[22px] leading-7 font-bold tabular-nums figure-md ${toneText(tone)}`}>{value}</div>
      {sub && <div className={`private mt-0.5 text-[13px] truncate ${subTone === 'neutral' ? 'text-[var(--text-muted)]' : toneText(subTone)}`}>{sub}</div>}
      {meta && <div className={`mt-0.5 text-[12px] truncate ${meta.stale ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{meta.stale ? `Stale · ${meta.text}` : meta.text}</div>}
    </>
  );
  const cls = 'block min-h-[88px] rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-3.5';
  return to ? <Link to={to} className={`${cls} transition-transform hover:bg-[var(--surface-2)] active:scale-[0.98] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>{body}</Link> : <div className={cls}>{body}</div>;
};

export default Tile;
