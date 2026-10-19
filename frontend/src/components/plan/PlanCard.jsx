import React from 'react';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import { formatClock } from '../../utils/formatters';
import { allowSummary, scoreLine, triggerLabel } from '../../utils/plan';
import { strategyName } from '../../utils/library';

/** AI > Activity: today's game plan (GET /plan/today) as a collapsed card. Renders nothing without a plan. */
const PlanCard = ({ data }) => {
  const plan = data?.plan;
  if (!plan) return null;
  const allow = allowSummary(plan);
  const score = scoreLine(data.scorecards);
  return (
    <Card title="Today's game plan" action={<Badge kind="neutral">{triggerLabel(plan.trigger)}{plan.version > 1 ? ` · revised ${plan.version - 1}×` : ''}</Badge>}>
      <details>
        <summary className="min-h-11 inline-flex items-center cursor-pointer text-[14px] font-semibold text-[var(--accent)]">
          {plan.skip_day ? 'Sitting today out' : `Up to ${plan.max_positions} new positions`}
        </summary>
        <div className="space-y-3 text-[15px] text-[var(--text)]">
          {plan.skip_day && <p className="text-[var(--warn)]">Sitting today out: no new intraday entries.</p>}
          {(plan.rationale || []).length > 0 && <ul className="space-y-1">{plan.rationale.map((line) => <li key={line}>{line}</li>)}</ul>}
          <p className="text-[13px] text-[var(--text-muted)]">Sizes at {Math.round(Number(plan.risk_multiplier ?? 1) * 100)}% of normal.</p>
          {allow.length > 0 && (
            <ul>
              {allow.map(({ symbol, strategies }) => (
                <li key={symbol} className="py-2 border-b border-[var(--border)] last:border-b-0">
                  <span className="font-medium">{symbol}</span>
                  <span className="ml-2 text-[13px] text-[var(--text-muted)]">{strategies.map(strategyName).join(' · ')}</span>
                </li>
              ))}
            </ul>
          )}
          {data.versions?.length > 1 && (
            <ul className="space-y-1 text-[13px] text-[var(--text-muted)]">
              {data.versions.map((v) => (
                <li key={v.version}>{formatClock(v.at)} · {triggerLabel(v.trigger)}{v.rationale?.[0] ? ` — ${v.rationale[0]}` : ''}</li>
              ))}
            </ul>
          )}
          {score && (
            <p className="text-[13px] text-[var(--text-muted)]">
              {score}{data.weeks_beating > 0 && ` · plan ahead ${data.weeks_beating} week${data.weeks_beating === 1 ? '' : 's'} in a row`}
            </p>
          )}
        </div>
      </details>
    </Card>
  );
};

export default PlanCard;
