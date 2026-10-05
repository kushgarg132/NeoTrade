import React, { useEffect, useState } from 'react';
import { Sheet } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { useReconnect, useTopic } from '../../hooks/useStream';

/**
 * Today's guardrail alerts: the limits the user set for themselves, checked
 * against their own broker. Prints nothing on a clear day.
 */
const GuardrailAlerts = () => {
  const [alerts, setAlerts] = useState([]);

  const load = () =>
    api
      .get(endpoints.guardrails.status)
      .then((res) => setAlerts(res.data.events || []))
      .catch(() => setAlerts([]));
  useEffect(() => {
    load();
  }, []);
  useReconnect(load);
  useTopic('guardrails', (message) => setAlerts((current) => [...current, message.data]));

  if (alerts.length === 0) return null;

  return (
    <Sheet title="Guardrails today" meta={`${alerts.length} alert${alerts.length === 1 ? '' : 's'}`}>
      <ul role="status">
        {alerts.map((alert, index) => (
          <li key={alert.key || index} className="py-2 border-b border-[var(--rule)] last:border-b-0">
            <p className="text-sm text-[var(--ink)]">{alert.title}</p>
            <p className="doc-meta normal-case mt-1">{alert.detail}</p>
          </li>
        ))}
      </ul>
    </Sheet>
  );
};

export default GuardrailAlerts;
