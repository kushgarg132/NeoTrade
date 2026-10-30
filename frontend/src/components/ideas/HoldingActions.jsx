import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Check, ChevronRight, Clock, Receipt } from 'lucide-react';
import Button from '../ui/Button';
import Empty from '../ui/Empty';
import DeltaChip from '../ui/DeltaChip';
import { inr } from '../ui/format';
import OrderTicket from '../trading/OrderTicket';
import { AiLabel, AmountText } from '../ai/AiSummary';
import useHoldings from '../money/useHoldings';
import { useLoad } from './useLoad';
import api, { endpoints } from '../../utils/api';
import { actionTarget } from '../../utils/mine';
import { stockPath } from '../../utils/stocks';
import { bareSymbol } from '../../utils/formatters';
import { eventDay, holdingButtons, signalText, triageHoldings } from '../../utils/ideas';

/** Where a row's own link leads: its page when it has one, else the stock's page. */
const rowLink = (a) => actionTarget(a).to || (a.symbol ? stockPath(a.symbol) : null);

// The dot before each signal on a stock card: an exit, a worse verdict or bad news is a loss, an add or a target a
// gain, a trim or a review a warning. The words beside it carry the meaning; the dot only sorts the eye.
const LOSS = 'bg-[var(--loss)]';
const GAIN = 'bg-[var(--gain)]';
const WARN = 'bg-[var(--warn)]';
const DOT = { stop_hit: LOSS, idea_exit: LOSS, verdict_worse: LOSS, bad_news: LOSS, target_hit: GAIN, add: GAIN, overweight: WARN, review_due: WARN };

const IconButton = ({ label, children, ...props }) => (
  <button type="button" aria-label={label} title={label}
    className="tap inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
    {...props}>
    {children}
  </button>
);

const ReadLink = ({ href }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" aria-label="Read the article" title="Read the article"
    className="tap inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
    <ArrowUpRight className="w-[18px] h-[18px]" aria-hidden="true" />
  </a>
);

const Note = ({ note }) => note ? (
  <div className="mt-2 rounded-[12px] bg-[var(--surface-2)] px-3 py-2">
    <AiLabel at={note.at} />
    <p className="text-[14px] leading-snug text-[var(--text)]"><AmountText text={note.text} /></p>
  </div>
) : null;

const SymbolLink = ({ symbol, className = '' }) => (
  <Link to={stockPath(symbol)} className={`inline-flex items-center gap-0.5 min-w-0 font-bold tracking-[-0.01em] text-[var(--text)] hover:underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[6px] ${className}`}>
    <span className="truncate">{bareSymbol(symbol)}</span>
    <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
  </Link>
);

const Band = ({ title, count, children }) => (
  <section className="space-y-3" aria-label={title}>
    <h3 className="flex items-baseline gap-2 text-[15px] font-semibold text-[var(--text)]">
      {title}<span className="text-[13px] font-medium tabular-nums text-[var(--text-muted)]">{count}</span>
    </h3>
    {children}
  </section>
);

/** One stock with something to act on: the position (value, weight, gain), every signal about it, one action. */
const StockCard = ({ stock, h, notes, onAct, onTicket }) => {
  const { items, symbol } = stock;
  const lead = items.find((a) => a.action?.type === 'ticket') || items.find((a) => a.kind !== 'bad_news') || items[0];
  const b = holdingButtons(lead);
  const to = rowLink(lead);
  const qty = lead.action?.quantity;
  const sell = lead.action?.side === 'SELL';
  return (
    <article className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-start justify-between gap-3">
        <SymbolLink symbol={symbol} className="text-[17px] -mt-0.5" />
        {h?.value != null && (
          <div className="shrink-0 text-right tabular-nums">
            <div className="private text-[15px] font-semibold text-[var(--text)]">{inr(h.value)}</div>
            {h.weight_pct != null && <div className="private text-[12px] text-[var(--text-muted)]">{h.weight_pct.toFixed(1)}% of account</div>}
          </div>
        )}
      </div>
      {h?.pnl != null && <div className="mt-1"><DeltaChip value={h.pnl} pct={h.pnl_pct} suffix="overall" /></div>}

      <ul className="mt-3 space-y-3">
        {items.map((a) => {
          const s = signalText(a);
          return (
            <li key={a.id} className="flex gap-3">
              <span aria-hidden="true" className={`mt-[7px] w-2 h-2 shrink-0 rounded-full ${DOT[a.kind] || 'bg-[var(--text-muted)]'}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1">
                  <p className="min-w-0 flex-1 text-[15px] leading-snug text-[var(--text)]">{s.text}</p>
                  {a.kind === 'bad_news' && a.action?.url && <span className="-my-2.5 -mr-2"><ReadLink href={a.action.url} /></span>}
                </div>
                {s.sub && <p className="text-[13px] text-[var(--text-muted)]">{s.sub}</p>}
                <Note note={notes?.[a.id]} />
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-4 flex items-center gap-2">
        {b.primary?.ticket && (
          <Button variant={sell ? 'danger' : 'primary'} className="flex-1 sm:flex-none sm:min-w-44" onClick={() => onTicket(actionTarget(lead).ticket)}>
            {b.primary.label}{qty ? ` ${qty}` : ''}
          </Button>
        )}
        {b.primary?.link && to && <Link to={to} className="flex-1 sm:flex-none"><Button className="w-full sm:min-w-44">{b.primary.label}</Button></Link>}
        <IconButton label={`${b.later}: hide for 7 days`} onClick={() => onAct('snooze', items)}><Clock className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
        <Button variant="secondary" className={b.primary ? 'px-3 text-[14px]' : 'flex-1 sm:flex-none'} onClick={() => onAct('dismiss', items)}>{b.dismiss}</Button>
      </div>
    </article>
  );
};

/**
 * Ideas → Holdings: every /mine/actions row about what you own, triaged (`utils/ideas.js::triageHoldings`).
 * Act now = one card per stock with its position and all its signals, one action; Keep an eye = news-only stocks
 * as rows; Coming up = dated rows, soonest first. Later snoozes 7 days, the dismiss label is the row's own
 * (`holdingButtons`); on a stock card both apply to every signal on it.
 */
const HoldingActions = ({ actions, onChanged }) => {
  const [ticket, setTicket] = useState(null);
  const { snapshot } = useHoldings();
  // The AI's one-liner under a row, read from what a job wrote. Missing, loading or failed all show nothing.
  const count = actions.length; // a new row may have a note by the next list refresh
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { data: notes } = useLoad(useCallback(() => api.get(endpoints.summaries.holdings).then((r) => r.data.notes), [count]));
  // The row's own words go along, so Handled can show what was hidden.
  const act = (verb, items) => Promise.all(items.map((a) => api.post(endpoints.mine[verb](a.id), { title: a.title, symbol: a.symbol, kind: a.kind })))
    .then(onChanged).catch(() => {});
  const held = Object.fromEntries((snapshot?.holdings || []).map((h) => [h.symbol, h]));
  const { act: now, watch, soon } = triageHoldings(actions);

  if (!now.length && !watch.length && !soon.length) {
    return (
      <div className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)]">
        <Empty title="You're clear." body="Exit alerts, verdict changes, bad news and results dates for what you own show up here."
          action={<Link to="/portfolio/holdings"><Button variant="secondary">Open holdings</Button></Link>} />
      </div>
    );
  }
  return (
    <div className="space-y-7">
      {now.length > 0 && (
        <Band title="Act now" count={now.length}>
          {now.map((s) => <StockCard key={s.symbol || s.items[0].id} stock={s} h={held[s.symbol]} notes={notes} onAct={act} onTicket={setTicket} />)}
        </Band>
      )}

      {watch.length > 0 && (
        <Band title="Keep an eye" count={watch.length}>
          <ul className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">
            {watch.flatMap((s) => s.items.map((a) => {
              const h = held[s.symbol];
              return (
                <li key={a.id} className="py-3 border-b border-[var(--border)] last:border-b-0">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2 min-w-0">
                        <SymbolLink symbol={s.symbol} className="text-[15px]" />
                        {h?.pnl_pct != null && (
                          <span className={`private shrink-0 text-[12px] font-medium tabular-nums ${h.pnl_pct < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>
                            {h.pnl_pct < 0 ? '▼' : '▲'} {Math.abs(h.pnl_pct).toFixed(1)}% overall
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-[14px] leading-snug text-[var(--text)]">{signalText(a).text}</p>
                      <Note note={notes?.[a.id]} />
                    </div>
                    <div className="flex shrink-0 -mr-2 -mt-1">
                      {a.action?.url && <ReadLink href={a.action.url} />}
                      <IconButton label={`${holdingButtons(a).dismiss}: hide this`} onClick={() => act('dismiss', [a])}><Check className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                    </div>
                  </div>
                </li>
              );
            }))}
          </ul>
        </Band>
      )}

      {soon.length > 0 && (
        <Band title="Coming up" count={soon.length}>
          <ul className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">
            {soon.map(({ item: a, date, label }) => {
              const d = date && eventDay(date);
              const b = holdingButtons(a);
              const to = rowLink(a);
              return (
                <li key={a.id} className="flex items-center gap-3 py-3 border-b border-[var(--border)] last:border-b-0">
                  <div className="w-12 shrink-0 rounded-[12px] bg-[var(--surface-2)] py-1.5 text-center tabular-nums" aria-hidden={d ? 'true' : undefined}>
                    {d ? (
                      <>
                        <div className="text-[11px] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">{d.dow}</div>
                        <div className="text-[17px] font-bold leading-tight text-[var(--text)]">{d.day}</div>
                        <div className="text-[12px] text-[var(--text-muted)]">{d.month}</div>
                      </>
                    ) : <Receipt className="mx-auto my-2 w-5 h-5 text-[var(--text-muted)]" aria-hidden="true" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    {label ? (
                      <p className="text-[15px] text-[var(--text)]">
                        {to ? <Link to={to} className="font-semibold hover:underline underline-offset-4">{bareSymbol(a.symbol)}</Link> : <span className="font-semibold">{bareSymbol(a.symbol)}</span>}
                        <span className="text-[var(--text-muted)]"> · {label}</span>
                        {d && <span className="sr-only"> on {d.dow} {d.day} {d.month}</span>}
                      </p>
                    ) : (
                      <p className="text-[15px] font-semibold text-[var(--text)]">{to ? <Link to={to} className="hover:underline underline-offset-4">{a.title}</Link> : a.title}</p>
                    )}
                    {a.detail && <p className="text-[13px] text-[var(--text-muted)]">{a.detail}</p>}
                    <Note note={notes?.[a.id]} />
                  </div>
                  <div className="flex shrink-0 -mr-2">
                    <IconButton label={`${b.later}: hide for 7 days`} onClick={() => act('snooze', [a])}><Clock className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                    <IconButton label={`${b.dismiss}: hide this`} onClick={() => act('dismiss', [a])}><Check className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                  </div>
                </li>
              );
            })}
          </ul>
        </Band>
      )}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onChanged} />}
    </div>
  );
};

export default HoldingActions;
