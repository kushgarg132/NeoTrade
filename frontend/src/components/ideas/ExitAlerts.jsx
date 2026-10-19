import React, { useState } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import OrderTicket from '../trading/OrderTicket';
import api, { endpoints } from '../../utils/api';
import { actionTarget } from '../../utils/mine';
import { bareSymbol } from '../../utils/formatters';

/** Exit alerts from /mine/actions (rows that open a sell ticket): Sell, Later (snooze 7 days), Dismiss. */
const ExitAlerts = ({ actions, onChanged }) => {
  const [ticket, setTicket] = useState(null);
  const act = (verb, id) => api.post(endpoints.mine[verb](id)).then(onChanged).catch(() => {});
  return (
    <Card title="Exit alerts">
      <ul>
        {actions.map((a) => (
          <li key={a.id} className="py-3 border-b border-[var(--border)] last:border-b-0">
            <div className="text-[15px] font-semibold text-[var(--text)]">{bareSymbol(a.symbol)} <span className="font-medium">{a.title}</span></div>
            {a.detail && <div className="text-[13px] text-[var(--text-muted)]">{a.detail}</div>}
            <div className="mt-2 grid grid-cols-3 gap-2">
              <Button variant="danger" onClick={() => setTicket(actionTarget(a).ticket)}>Sell</Button>
              <Button variant="secondary" onClick={() => act('snooze', a.id)}>Later</Button>
              <Button variant="secondary" onClick={() => act('dismiss', a.id)}>Dismiss</Button>
            </div>
          </li>
        ))}
      </ul>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onChanged} />}
    </Card>
  );
};

export default ExitAlerts;
