import React, { useEffect, useState } from 'react';
import Card from '../ui/Card';
import api, { endpoints } from '../../utils/api';
import { useReconnect, useTopic } from '../../hooks/useStream';

/** Today's guardrail alerts: the limits the user set for themselves, checked against their own broker. Nothing on a clear day. */
const GuardrailAlerts = () => {
  const [alerts, setAlerts] = useState([]);

  const load = () =>
    api.get(endpoints.guardrails.status).then((res) => setAlerts(res.data.events || [])).catch(() => setAlerts([]));
  useEffect(() => {
    load();
  }, []);
  useReconnect(load);
  useTopic('guardrails', (message) => setAlerts((current) => [...current, message.data]));

  if (alerts.length === 0) return null;

  return (
    <Card title="Guardrails today" action={<span className="text-[13px] text-[var(--text-muted)]">{alerts.length} alert{alerts.length === 1 ? '' : 's'}</span>}>
      <ul role="status">
        {alerts.map((alert, index) => (
          <li key={alert.key || index} className="py-2 border-b border-[var(--border)] last:border-b-0">
            <p className="text-[15px] text-[var(--text)]">{alert.title}</p>
            <p className="text-[13px] text-[var(--text-muted)] mt-0.5">{alert.detail}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
};

export default GuardrailAlerts;
