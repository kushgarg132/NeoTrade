import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import api, { endpoints } from '../../utils/api';

/** Where alerts reach you. The Telegram bot and chat link are set up with the guardrails, under Limits. */
const Alerts = () => {
  const [state, setState] = useState({ telegram: null, error: false });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    api.get(endpoints.guardrails.status)
      .then((res) => live && setState({ telegram: res.data.telegram || {}, error: false }))
      .catch(() => live && setState({ telegram: null, error: true }));
    return () => { live = false; };
  }, [tick]);
  const retry = useCallback(() => { setState({ telegram: null, error: false }); setTick((t) => t + 1); }, []);
  const { telegram, error } = state;
  return (
    <Card title="Telegram alerts">
      {error ? <ErrorLine message="Could not load alert status." onRetry={retry} />
        : !telegram ? <Skeleton rows={2} />
        : (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge kind={telegram.linked ? 'proven' : 'neutral'}>{telegram.linked ? 'Linked' : 'Not linked'}</Badge>
              {telegram.own_bot && <span className="text-[13px] text-[var(--text-muted)]">via @{telegram.own_bot}</span>}
            </div>
            <p className="text-[14px] text-[var(--text-muted)]">
              Guardrail breaches, trade ideas and the daily brief arrive on Telegram once linked.
            </p>
            <Link to="/settings?tab=limits" className="inline-flex items-center min-h-11 text-[15px] font-semibold text-[var(--accent)]">
              {telegram.linked ? 'Manage in Limits' : 'Link Telegram in Limits'}
            </Link>
          </div>
        )}
    </Card>
  );
};

export default Alerts;
