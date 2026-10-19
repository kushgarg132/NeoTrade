import React from 'react';
import { Link } from 'react-router-dom';
import { toneText } from './tone';

/** A home-screen tile: label, one headline figure, a sub-line. A tile with `to` is one tap. */
const Tile = ({ title, value, sub, tone = 'neutral', to, icon: Icon }) => {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)]">
        {Icon && <Icon className="w-4 h-4" aria-hidden="true" />}
        <span>{title}</span>
      </div>
      <div className={`private mt-1 text-[22px] leading-7 font-bold tabular-nums figure-md ${toneText(tone)}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[13px] text-[var(--text-muted)]">{sub}</div>}
    </>
  );
  const cls = 'block min-h-[88px] rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-3.5';
  return to ? <Link to={to} className={`${cls} active:bg-[var(--surface-2)]`}>{body}</Link> : <div className={cls}>{body}</div>;
};

export default Tile;
