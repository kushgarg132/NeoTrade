import React from 'react';
import { Link } from 'react-router-dom';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Hero from '../ui/Hero';
import DeltaChip from '../ui/DeltaChip';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

/**
 * The glance: your account's value, today's change in rupees and percent, and how that sits against NIFTY.
 * `headline` is /mine/overview's headline (or /today's pulse), `nifty` the NIFTY 50 row of /market/indices.
 * Percents arrive as 1.65 (= 1.65%).
 */
const HeroRow = ({ headline, nifty, phase, meta, failed, onRetry }) => {
  if (failed && (!headline || typeof headline.value !== 'number')) return <ErrorLine message="Couldn't load your account value." onRetry={onRetry} />;
  if (!headline || typeof headline.value !== 'number') {
    return (
      <Empty title="No account value yet" body="Your value and today's change show here once a broker is connected."
             action={<Link to="/settings/brokers" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Connect your broker</Link>} />
    );
  }
  const day = phase === 'session' ? 'Today' : 'Last session';
  const mine = headline.day_change_pct;
  const idx = nifty && typeof nifty.percent === 'number' ? nifty.percent : null;
  const gap = typeof mine === 'number' && idx !== null ? mine - idx : null;
  const sgnPts = (g) => `${g < 0 ? '-' : '+'}${Math.abs(g).toFixed(2)} pts`;
  return (
    <Hero to="/money" label="Your account" value={headline.value}
          change={<DeltaChip value={headline.day_change} pct={mine} suffix={day.toLowerCase()} />}>
      {idx !== null && (
        <div className="mt-3 text-[14px] tabular-nums text-[var(--text-muted)]">
          NIFTY {pct(idx / 100, { sign: true })}
          {gap !== null && <> · you <span className={`font-semibold ${toneText(tone(gap))}`}>{sgnPts(gap)}</span></>}
        </div>
      )}
      {meta && <div className={`mt-0.5 text-[12px] ${meta.stale ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{meta.text}</div>}
    </Hero>
  );
};

export default HeroRow;
