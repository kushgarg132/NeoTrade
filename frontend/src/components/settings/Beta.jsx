import React, { useEffect, useState } from 'react';
import { Sheet } from './Panel';
import api, { endpoints } from '../../utils/api';
import { Row } from './Fields';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';

const BETA_ROWS = [
  ['users', 'Signed up'],
  ['users_with_trades', 'With trades in the journal'],
  ['weekly_active', 'Opened the journal in the last 7 days'],
  ['returned_from_last_week', 'Came back from the week before'],
  ['guardrails_on', 'Guardrails on'],
  ['telegram_linked', 'Telegram linked'],
];

/** Admin only: Phase 12's question — do beta users come back? */
const BetaSheet = () => {
  const [metrics, setMetrics] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => api
    .get(endpoints.journal.betaMetrics)
    .then((res) => { setMetrics(res.data); setFailed(false); })
    .catch(() => setFailed(true));
  useEffect(() => { load(); }, []);

  if (failed) return <Sheet title="Beta" meta="All users"><ErrorLine message="Couldn't load beta metrics." onRetry={load} /></Sheet>;
  if (!metrics) return <Sheet title="Beta" meta="All users"><Skeleton rows={4} /></Sheet>;

  return (
    <Sheet title="Beta" meta="All users">
      {BETA_ROWS.map(([key, label]) => (
        <Row key={key} label={label}>
          <span className="figure-md text-[15px] tabular-nums">
            {metrics[key]}
            {key === 'returned_from_last_week' && ` of ${metrics.active_last_week}`}
          </span>
        </Row>
      ))}
      <Row label="Losing days followed by a journal visit" hint="Within 3 days of the loss.">
        <span className="figure-md text-[15px] tabular-nums">
          {metrics.losing_days_followed_by_open} of {metrics.losing_days}
        </span>
      </Row>
    </Sheet>
  );
};

export default BetaSheet;
