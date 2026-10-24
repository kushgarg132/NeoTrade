import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Empty from '../ui/Empty';
import OrderTicket from '../trading/OrderTicket';
import { AiLabel, AmountText } from '../ai/AiSummary';
import { useLoad } from './useLoad';
import api, { endpoints } from '../../utils/api';
import { actionTarget } from '../../utils/mine';
import { stockPath } from '../../utils/stocks';
import { groupHoldingActions } from '../../utils/ideas';

/** Where tapping a row leads: its own page when it has one, else the stock's page. */
const rowLink = (a) => actionTarget(a).to || (a.symbol ? stockPath(a.symbol) : null);

/**
 * Your holdings: every /mine/actions row about what you own (exit alerts, bad news, results soon...),
 * grouped under a plain title. Sell (when the row carries an order), Later (snooze 7 days), Dismiss.
 */
const HoldingActions = ({ actions, onChanged }) => {
  const [ticket, setTicket] = useState(null);
  // The AI's one-liner under a bad-news / results-soon row, read from what a job wrote. Missing, loading
  // or failed all show nothing: the row stands on its own.
  const count = actions.length; // a new row may have a note by the next list refresh
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { data: notes } = useLoad(useCallback(() => api.get(endpoints.summaries.holdings).then((r) => r.data.notes), [count]));
  const act = (verb, id) => api.post(endpoints.mine[verb](id)).then(onChanged).catch(() => {});
  const groups = groupHoldingActions(actions);
  if (!groups.length) {
    return (
      <Card title="Your holdings">
        <Empty title="Nothing needs you on your holdings" body="Stop and target hits, bad news and results dates for what you own in your broker account show up here."
          action={<Link to="/money"><Button variant="secondary">Open Money</Button></Link>} />
      </Card>
    );
  }
  return (
    <Card title="Your holdings">
      {groups.map((g) => (
        <div key={g.title} className="mb-2 last:mb-0">
          <h3 className="text-[13px] font-semibold text-[var(--text-muted)]">{g.title}</h3>
          <ul>
            {g.items.map((a) => {
              const to = rowLink(a);
              const body = (
                <>
                  <div className="min-w-0 flex-1">
                    <div className="text-[15px] font-semibold text-[var(--text)]">{a.title}</div>
                    {a.detail && <div className="text-[13px] text-[var(--text-muted)]">{a.detail}</div>}
                  </div>
                  {to && <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
                </>
              );
              return (
                <li key={a.id} className="py-3 border-b border-[var(--border)] last:border-b-0">
                  {to
                    ? <Link to={to} className="flex items-center gap-3 min-h-11 active:bg-[var(--surface-2)]">{body}</Link>
                    : <div className="flex items-center gap-3">{body}</div>}
                  {notes?.[a.id] && (
                    <div className="mt-1.5 rounded-[12px] bg-[var(--surface-2)] px-3 py-2">
                      <AiLabel at={notes[a.id].at} />
                      <p className="text-[14px] text-[var(--text)]"><AmountText text={notes[a.id].text} /></p>
                    </div>
                  )}
                  <div className={`mt-2 grid gap-2 ${a.action?.type === 'ticket' ? 'grid-cols-3' : 'grid-cols-2'}`}>
                    {a.action?.type === 'ticket' && <Button variant="danger" onClick={() => setTicket(actionTarget(a).ticket)}>{a.action.side === 'BUY' ? 'Buy' : 'Sell'}</Button>}
                    <Button variant="secondary" onClick={() => act('snooze', a.id)}>Later</Button>
                    <Button variant="secondary" onClick={() => act('dismiss', a.id)}>Dismiss</Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onChanged} />}
    </Card>
  );
};

export default HoldingActions;
