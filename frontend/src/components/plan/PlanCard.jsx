import React, { useEffect, useState } from 'react';
import { Sheet, Ruling, Scrip } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { formatClock } from '../../utils/formatters';
import { allowSummary, scoreLine, triggerLabel } from '../../utils/plan';

/** AI → Activity: today's game plan (backend/plan/), its revisions, and how plans score against no plan. */
const PlanCard = () => {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api.get(endpoints.planToday).then((res) => setData(res.data)).catch(() => setFailed(true));
  }, []);

  if (failed) return null;
  const plan = data?.plan;
  const meta = plan ? `${triggerLabel(plan.trigger)} · v${plan.version}` : undefined;
  return (
    <Sheet title="Today's plan" meta={meta}>
      {data === null ? <Ruling rows={3} /> : !plan ? (
        <p className="doc-meta normal-case">No plan today. Plans are made at 08:45 IST for auto-run intraday accounts.</p>
      ) : (
        <div className="space-y-3 text-sm">
          {plan.skip_day && <p className="field-label text-down">Sitting today out: no new intraday entries.</p>}
          {(plan.rationale || []).length > 0 && (
            <ul className="space-y-1">{plan.rationale.map((line) => <li key={line}>{line}</li>)}</ul>
          )}
          <p className="doc-meta normal-case">
            Risk {Number(plan.risk_multiplier ?? 1).toFixed(2)}× · up to {plan.max_positions} new positions
            {(plan.add_symbols || []).length > 0 && ` · added ${plan.add_symbols.join(', ')}`}
          </p>
          {allowSummary(plan).length > 0 && (
            <ul className="divide-y divide-[var(--rule)]">
              {allowSummary(plan).map(({ symbol, strategies }) => (
                <li key={symbol} className="py-1.5 flex flex-wrap items-baseline gap-x-2">
                  <Scrip symbol={symbol} />
                  <span className="doc-meta normal-case">{strategies.join(' · ')}</span>
                </li>
              ))}
            </ul>
          )}
          {data.versions.length > 1 && (
            <div>
              <p className="field-label mb-1">Revisions</p>
              <ul className="space-y-1">
                {data.versions.map((v) => (
                  <li key={v.version} className="doc-meta normal-case">
                    {formatClock(v.at)} · {triggerLabel(v.trigger)}{v.rationale?.[0] ? ` — ${v.rationale[0]}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {data && scoreLine(data.scorecards) && (
        <p className="doc-meta normal-case mt-3 pt-2 border-t border-[var(--rule)]">
          {scoreLine(data.scorecards)}
          {data.weeks_beating > 0 && ` · plan ahead ${data.weeks_beating} week${data.weeks_beating === 1 ? '' : 's'} in a row`}
        </p>
      )}
    </Sheet>
  );
};

export default PlanCard;
