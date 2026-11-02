import React from 'react';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import { headline, pct } from '../../utils/plan';

const Row = ({ left, right, warn }) => (
  <li className="py-2 border-b border-[var(--border)] last:border-b-0 flex justify-between gap-3">
    <span className="font-medium">{left}</span>
    <span className={`text-[13px] ${warn ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{right}</span>
  </li>
);

/** AI > Activity: the daily rotation plan (GET /plan/today) as a collapsed card. Renders nothing without a plan. */
const PlanCard = ({ data }) => {
  const plan = data?.plan;
  if (!plan) return null;
  return (
    <Card title={`AI plan · ${plan.date}`} action={<Badge kind="neutral">{plan.live ? 'Live' : 'Paper'} · week {plan.week}</Badge>}>
      <details>
        <summary className="min-h-11 inline-flex items-center cursor-pointer text-[14px] font-semibold text-[var(--accent)]">
          {headline(plan)}
        </summary>
        <div className="space-y-3 text-[15px] text-[var(--text)]">
          <p className="text-[13px] text-[var(--text-muted)]">
            Nifty {pct(plan.nifty_vs_200dma)} vs its 200-day average · {Math.round((plan.breadth || 0) * 100)}% of stocks above their 50-day.
            {!plan.enabled && ' Autopilot off: no new buys.'}
          </p>
          {(plan.sells?.length > 0 || plan.buys?.length > 0) && (
            <ul>
              {plan.sells.map((s) => <Row key={`s${s.symbol}`} left={`Sell ${s.symbol}`} right={s.why === 'risk_off' ? 'risk-off, to cash' : 'out of the top ranks'} />)}
              {plan.buys.map((b) => <Row key={`b${b.symbol}`} left={`Buy ${b.symbol}`} right={b.blocked ? `blocked: ${b.blocked}` : `${Math.round(b.weight * 100)}% of the book`} warn={!!b.blocked} />)}
            </ul>
          )}
          {plan.holdings?.length > 0 && (
            <ul>
              {plan.holdings.map((h) => (
                <Row key={h.symbol} left={h.symbol} warn={!!h.news}
                  right={`${pct(h.pnl_pct)}${h.rank ? ` · rank ${h.rank}` : ''}${h.news ? ` · ${h.news}` : ''}`} />
              ))}
            </ul>
          )}
          {Object.keys(plan.news_vetoed || {}).length > 0 && (
            <p className="text-[13px] text-[var(--text-muted)]">
              Skipped on news: {Object.entries(plan.news_vetoed).map(([s, why]) => `${s} (${why})`).join(', ')}
            </p>
          )}
          <p className="text-[13px] text-[var(--text-muted)]">Next rebalance {plan.next_rebalance}.</p>
        </div>
      </details>
    </Card>
  );
};

export default PlanCard;
