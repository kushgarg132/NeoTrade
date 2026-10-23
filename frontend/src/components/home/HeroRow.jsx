import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Empty from '../ui/Empty';
import { inr, pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

/**
 * The glance: your account's value, today's change in rupees and percent, and how that sits against NIFTY.
 * `headline` is /mine/overview's headline (or /today's pulse), `nifty` the NIFTY 50 row of /market/indices.
 * Percents arrive as 1.65 (= 1.65%).
 */
const HeroRow = ({ headline, nifty, phase, meta }) => {
  if (!headline || typeof headline.value !== 'number') {
    return (
      <Empty title="No account value yet" body="Your value and today's change show here once a broker is connected."
             action={<Link to="/settings?tab=accounts" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Connect your broker</Link>} />
    );
  }
  const day = phase === 'session' ? 'Today' : 'Last session';
  const mine = headline.day_change_pct;
  const idx = nifty && typeof nifty.percent === 'number' ? nifty.percent : null;
  const gap = typeof mine === 'number' && idx !== null ? mine - idx : null;
  const sgnPts = (g) => `${g < 0 ? '-' : '+'}${Math.abs(g).toFixed(2)} pts`;
  return (
    <Link to="/money" className="block rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-4 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
      <div className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)]">
        <span className="flex-1">Your account</span>
        <ChevronRight className="w-4 h-4 shrink-0" aria-hidden="true" />
      </div>
      <div className="private figure-md mt-1 text-[32px] leading-9 font-bold tabular-nums text-[var(--text)]">{inr(headline.value)}</div>
      <div className={`private mt-1 text-[17px] font-semibold tabular-nums ${toneText(tone(headline.day_change))}`}>
        {day} {inr(headline.day_change, { sign: true })}
        {typeof mine === 'number' && ` (${pct(mine / 100, { sign: true })})`}
      </div>
      {idx !== null && (
        <div className="mt-0.5 text-[14px] tabular-nums text-[var(--text-muted)]">
          NIFTY {pct(idx / 100, { sign: true })}
          {gap !== null && <> · you <span className={`font-semibold ${toneText(tone(gap))}`}>{sgnPts(gap)}</span></>}
        </div>
      )}
      {meta && <div className={`mt-0.5 text-[12px] ${meta.stale ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{meta.text}</div>}
    </Link>
  );
};

export default HeroRow;
