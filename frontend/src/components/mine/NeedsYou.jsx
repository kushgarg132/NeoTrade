import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { X, Clock } from 'lucide-react';
import { Sheet, Empty, Scrip } from '../doc/Doc';
import OrderTicket from '../trading/OrderTicket';
import SuggestionRecord from '../suggestions/SuggestionRecord';
import api, { endpoints } from '../../utils/api';
import { actionTarget } from '../../utils/mine';

const LINK = 'field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center';
const ICON = 'min-h-9 min-w-9 inline-flex items-center justify-center text-[var(--ink-faint)] hover:text-[var(--ink)]';
const VERB = { ticket: 'Open ticket', stock: 'Open', tax: 'Open', rebalance: 'Plan' };

/**
 * The ranked list from GET /mine/actions. Every row can be dismissed or
 * snoozed 7 days; a ticket row opens the order ticket, an idea row is the
 * proposal itself with approve / decline.
 */
const NeedsYou = ({ actions, onChanged, limit }) => {
  const [ticket, setTicket] = useState(null);
  const [ideas, setIdeas] = useState({});
  const [all, setAll] = useState(false);
  const rows = limit && !all ? actions.slice(0, limit) : actions;
  const wantIdeas = rows.some((a) => a.action?.type === 'idea');

  useEffect(() => {
    if (!wantIdeas) return;
    api
      .get(endpoints.suggestions.list({ status: 'PENDING', mode: 'LONGTERM' }))
      .then((res) => setIdeas(Object.fromEntries(res.data.map((s) => [s.id, s]))))
      .catch(() => setIdeas({}));
  }, [wantIdeas, actions]);

  const act = (verb, id) => api.post(endpoints.mine[verb](id)).then(onChanged).catch(() => {});
  const decide = (s, url) => api.post(url, url.endsWith('/reject') ? {} : undefined).then(onChanged);

  return (
    <Sheet title="Needs you" meta={actions.length ? `${actions.length}` : null}>
      {actions.length === 0 ? (
        <Empty title="You're clear." detail="Nothing on your holdings needs a decision right now." />
      ) : (
        <ul className="divide-y divide-[var(--rule)]">
          {rows.map((a) => {
            const target = actionTarget(a);
            const idea = a.action?.type === 'idea' ? ideas[a.action.suggestion_id] : null;
            return (
              <li key={a.id} className="py-2.5">
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold">
                      {a.symbol && <Scrip symbol={a.symbol} />} <span className="ml-1">{a.title}</span>
                    </p>
                    {a.detail && <p className="text-sm text-[var(--ink-soft)]">{a.detail}</p>}
                  </div>
                  {target.to && !target.idea && (
                    <Link to={target.to} className={LINK}>
                      {VERB[a.action.type]} ›
                    </Link>
                  )}
                  {target.ticket && (
                    <button type="button" className={LINK} onClick={() => setTicket(target.ticket)}>
                      {VERB.ticket} ›
                    </button>
                  )}
                  <button type="button" aria-label="Snooze 7 days" title="Snooze 7 days" className={ICON} onClick={() => act('snooze', a.id)}>
                    <Clock className="w-4 h-4" />
                  </button>
                  <button type="button" aria-label="Dismiss" title="Dismiss" className={ICON} onClick={() => act('dismiss', a.id)}>
                    <X className="w-4 h-4" />
                  </button>
                </div>
                {idea && (
                  <div className="mt-2">
                    <SuggestionRecord
                      suggestion={idea}
                      hasMine
                      onApproveLive={() => decide(idea, endpoints.suggestions.approveLive(idea.id))}
                      onReject={() => decide(idea, endpoints.suggestions.reject(idea.id))}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {limit && actions.length > limit && (
        <button type="button" onClick={() => setAll((v) => !v)} className="w-full py-3 field-label text-[var(--stamp)] hover:bg-[var(--paper-sunk)]">
          {all ? `Show first ${limit}` : `Show ${actions.length - limit} more`}
        </button>
      )}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onChanged} />}
    </Sheet>
  );
};

export default NeedsYou;
