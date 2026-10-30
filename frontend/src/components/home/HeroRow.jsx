import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Hero from '../ui/Hero';
import DeltaChip from '../ui/DeltaChip';
import { inr, pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { vsNifty } from '../../utils/home';

/**
 * "Where am I?": your account's value and today's change, today against NIFTY in words, the overall gain with XIRR
 * against NIFTY's on the same cash flows and `children` (the goal line) folded under "Goal and XIRR". `headline` is /mine/overview's headline
 * (or /today's pulse), `nifty` the NIFTY 50 row of /market/indices. Percents arrive as 1.65 (= 1.65%), XIRR as 0.06.
 */
const HeroRow = ({ headline, nifty, phase, meta, failed, onRetry, children }) => {
  if (failed && (!headline || typeof headline.value !== 'number')) return <ErrorLine message="Couldn't load your account value." onRetry={onRetry} />;
  if (!headline || typeof headline.value !== 'number') {
    return (
      <Empty title="No account value yet" body="Your value and today's change show here once a broker is connected."
             action={<Link to="/settings/brokers" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">Connect your broker</Link>} />
    );
  }
  const day = phase === 'session' ? 'today' : 'last session';
  const idx = nifty && typeof nifty.percent === 'number' ? nifty.percent : null;
  const vs = vsNifty(headline.day_change_pct, idx);
  const x = headline.xirr;
  const nx = headline.nifty_xirr;
  const xAhead = typeof x === 'number' && typeof nx === 'number' ? x - nx : null;
  return (
    <Hero label={(
      <span className="flex items-center justify-between gap-3">
        Your account
        <Link to="/money" className="inline-flex items-center gap-0.5 min-h-11 -my-3 text-[13px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[8px]">
          Your money <ChevronRight className="w-4 h-4" aria-hidden="true" />
        </Link>
      </span>
    )} value={headline.value}
          change={<DeltaChip value={headline.day_change} pct={headline.day_change_pct} suffix={day} />}>
      {vs && (
        <p className="mt-3 text-[15px] text-[var(--text)]">
          <span className={`font-semibold ${toneText(tone(vs.gap))}`}>{vs.text}</span>
          <span className="text-[var(--text-muted)] tabular-nums"> · NIFTY {pct(idx / 100, { sign: true })}</span>
        </p>
      )}
      {typeof headline.pnl === 'number' && (
        <p className="mt-1 text-[13px] tabular-nums text-[var(--text-muted)]">
          Overall <span className={`private font-semibold ${toneText(tone(headline.pnl))}`}>{inr(headline.pnl, { sign: true })}</span>
          {typeof headline.pnl_pct === 'number' && <> ({pct(headline.pnl_pct / 100, { sign: true, dp: 1 })})</>}
        </p>
      )}
      {meta && <div className={`mt-1 text-[12px] ${meta.stale ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{meta.text}</div>}
      {(xAhead !== null || children) && (
        // The glance stops at the line above; XIRR and the goal are a tap away (native <details>, keyboard included).
        <details className="group mt-3 border-t border-[var(--border)]">
          <summary className="flex items-center justify-between min-h-11 cursor-pointer list-none text-[13px] font-semibold text-[var(--text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[8px] [&::-webkit-details-marker]:hidden">
            {children ? 'Goal and XIRR' : 'XIRR'}
            <ChevronDown className="w-4 h-4 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          {xAhead !== null && (
            <p className="pb-3 text-[13px] tabular-nums text-[var(--text-muted)]">
              XIRR {pct(x, { sign: true, dp: 1 })} vs NIFTY {pct(nx, { sign: true, dp: 1 })}{' '}
              <span className={`font-semibold ${toneText(tone(xAhead))}`}>{xAhead >= 0 ? 'ahead' : 'behind'}</span>
            </p>
          )}
          {children && <div className="pb-1">{children}</div>}
        </details>
      )}
    </Hero>
  );
};

export default HeroRow;
