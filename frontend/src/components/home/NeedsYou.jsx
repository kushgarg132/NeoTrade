import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Lightbulb } from 'lucide-react';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import OrderTicket from '../trading/OrderTicket';
import { actionTarget } from '../../utils/mine';
import { stockPath } from '../../utils/stocks';
import { bareSymbol } from '../../utils/formatters';
import { actNowCount, holdingButtons, holdingActions, signalText, triageHoldings } from '../../utils/ideas';

const SHOWN = 3;
const DOT = { verdict_worse: 'bg-[var(--loss)]', stop_hit: 'bg-[var(--loss)]', idea_exit: 'bg-[var(--loss)]', target_hit: 'bg-[var(--gain)]', add: 'bg-[var(--gain)]' };

/**
 * Home's "anything waiting for me?": the first SHOWN stocks to act on (Ideas → Holdings' own triage, so both agree on
 * order), each with its one action ("Sell 213" opens the order ticket), then the ideas waiting, then "See all N".
 * `need` is useNeedCount's result.
 */
const NeedsYou = ({ need, isAdmin, onDone }) => {
  const [ticket, setTicket] = useState(null);
  const all = isAdmin ? '/ideas?tab=holdings' : '/money';
  if (!need.loaded) return need.error ? <ErrorLine message="Couldn't load what needs you." onRetry={need.reload} /> : <Skeleton rows={3} />;
  const { act } = triageHoldings(need.actions);
  const top = act.slice(0, SHOWN);
  const ideas = need.ideas.length;
  const shown = top.reduce((n, s) => n + s.items.filter((a) => actNowCount([a])).length, 0);
  const more = actNowCount(need.actions) - shown;
  const fyi = holdingActions(need.actions).length - actNowCount(need.actions);
  return (
    <section aria-label="Needs you">
      <div className="mb-2 flex items-baseline justify-between gap-3 px-1">
        <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">
          Needs you {need.count > 0 && <span className="text-[15px] font-medium tabular-nums text-[var(--text-muted)]">{need.count}</span>}
        </h2>
        {need.count > 0 && (
          <Link to={all} className="inline-flex items-center gap-0.5 min-h-11 -my-3 text-[14px] font-semibold text-[var(--accent)]">
            See all <ChevronRight className="w-4 h-4" aria-hidden="true" />
          </Link>
        )}
      </div>
      <div className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">
        {need.count === 0 && <p className="py-4 text-[15px] text-[var(--text)]">You're clear. <span className="text-[var(--text-muted)]">Nothing on your holdings or ideas needs a decision.</span></p>}
        {top.map((s) => {
          const lead = s.items.find((a) => a.action?.type === 'ticket') || s.items[0];
          const b = holdingButtons(lead);
          const t = actionTarget(lead).ticket;
          const stamp = b.primary?.ticket && t;
          return (
            <div key={s.symbol || lead.id} className="flex items-center gap-3 py-3 border-b border-[var(--border)] last:border-b-0">
              {!stamp && <span aria-hidden="true" className={`w-2 h-2 shrink-0 rounded-full ${DOT[lead.kind] || 'bg-[var(--warn)]'}`} />}
              <Link to={s.symbol ? stockPath(s.symbol) : all} className="min-w-0 flex-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[8px]">
                <div className="text-[15px] font-bold text-[var(--text)] truncate">{bareSymbol(s.symbol) || lead.title}</div>
                <div className="text-[13px] text-[var(--text-muted)] line-clamp-2">
                  {signalText(lead).text}{s.items.length > 1 ? ` · +${s.items.length - 1} more` : ''}
                </div>
              </Link>
              {stamp && (
                // A stamp, side over quantity, tinted by side (it replaces the dot). It opens the ticket, which is
                // the review; solid red waits for the ticket's final confirm.
                <button
                  type="button"
                  onClick={() => setTicket(t)}
                  aria-label={`${b.primary.label} ${lead.action.quantity} shares, opens the order ticket`}
                  className={`tap shrink-0 w-14 h-12 rounded-[12px] grid place-content-center justify-items-center gap-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                    b.primary.label === 'Sell' ? 'bg-[var(--loss-soft)] text-[var(--loss)]' : 'bg-[var(--gain-soft)] text-[var(--gain)]'
                  }`}
                >
                  <span className="text-[10px] font-extrabold tracking-[0.08em] uppercase leading-none">{b.primary.label}</span>
                  <span className="text-[17px] font-extrabold leading-none tabular-nums">{lead.action.quantity}</span>
                </button>
              )}
            </div>
          );
        })}
        {ideas > 0 && (
          <Link to="/ideas" className="tap flex items-center gap-3 py-3 border-b border-[var(--border)] last:border-b-0 hover:opacity-80">
            <Lightbulb className="w-4 h-4 shrink-0 text-[var(--accent)]" aria-hidden="true" />
            <span className="flex-1 text-[15px] text-[var(--text)]">{ideas} idea{ideas === 1 ? '' : 's'} waiting</span>
            <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
          </Link>
        )}
        {more > 0 && (
          <Link to={all} className="tap flex items-center gap-3 py-3 border-b border-[var(--border)] last:border-b-0 hover:opacity-80">
            <span className="flex-1 text-[15px] text-[var(--text)]">{more} more to decide on your holdings</span>
            <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
          </Link>
        )}
        {fyi > 0 && (
          <Link to={all} className="tap flex items-center gap-3 py-3 hover:opacity-80">
            <span className="flex-1 text-[14px] text-[var(--text-muted)]">{fyi} FYI: news, results, dividends, tax dates</span>
            <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
          </Link>
        )}
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onDone} />}
    </section>
  );
};

export default NeedsYou;
