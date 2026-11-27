import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Check, ChevronDown, Clock, Receipt } from 'lucide-react';
import Button from '../ui/Button';
import DeltaChip from '../ui/DeltaChip';
import { inr } from '../ui/format';
import OrderTicket from '../trading/OrderTicket';
import { AiLabel, AmountText } from '../ai/AiSummary';
import { ImpactChips, NewsLink } from '../common/NewsImpacts';
import useHoldings from '../money/useHoldings';
import { useLoad } from './useLoad';
import Stamp from './Stamp';
import api, { endpoints } from '../../utils/api';
import { actionTarget } from '../../utils/mine';
import { stockPath } from '../../utils/stocks';
import { bareSymbol } from '../../utils/formatters';
import { eventDay, holdingButtons, signalText, triageHoldings } from '../../utils/ideas';
import StockIcon from '../ui/StockIcon';

/** Where a row's own link leads: its page when it has one, else the stock's page. */
const rowLink = (a) => actionTarget(a).to || (a.symbol ? stockPath(a.symbol) : null);

// The dot before each signal: an exit, a worse verdict or bad news is a loss, an add or a target a gain, a trim or a
// review a warning. The words carry the meaning; the dot only sorts the eye.
const LOSS = 'bg-[var(--loss)]';
const GAIN = 'bg-[var(--gain)]';
const WARN = 'bg-[var(--warn)]';
const DOT = { stop_hit: LOSS, idea_exit: LOSS, verdict_worse: LOSS, bad_news: LOSS, target_hit: GAIN, add: GAIN, overweight: WARN, review_due: WARN };
const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';

const IconButton = ({ label, children, ...props }) => (
  <button type="button" aria-label={label} title={label}
    className={`tap inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] ${ring}`}
    {...props}>
    {children}
  </button>
);

/** A news row's way out: the story's analysis page when stored (it links the article too), else the article. */
const ReadLink = ({ action }) => (
  <NewsLink id={action.news_id} url={action.url}
    className={`tap inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] ${ring}`}>
    <ArrowUpRight className="w-[18px] h-[18px]" aria-label={action.news_id ? 'Open the news analysis' : 'Read the article'} />
  </NewsLink>
);

const Note = ({ note }) => note ? (
  <div className="mt-2">
    <AiLabel at={note.at} />
    <p className="text-[14px] leading-snug text-[var(--text)]"><AmountText text={note.text} /></p>
  </div>
) : null;

/**
 * One stock to decide on: logo, symbol and its lead signal; the stamp (Sell 52 / Buy 7) opens the order ticket.
 * Tapping the row opens the rest under it: the position, every signal with its AI note, and Later / dismiss
 * (both apply to every signal on the stock).
 */
const StockRow = ({ stock, h, notes, open, onToggle, onAct, onTicket }) => {
  const { items, symbol } = stock;
  const lead = items.find((a) => a.action?.type === 'ticket') || items.find((a) => a.kind !== 'bad_news') || items[0];
  const b = holdingButtons(lead);
  const ticket = b.primary?.ticket && actionTarget(lead).ticket;
  const to = rowLink(lead);
  const more = items.length - 1;
  return (
    <li className="border-b border-[var(--border)] last:border-b-0">
      {/* The row-wide toggle sits under the content (pointer-events off), so the name link and the stamp stay tappable. */}
      <div className="relative flex items-center gap-3 py-3">
        <button type="button" aria-expanded={open} aria-label={`${bareSymbol(symbol) || lead.title}: show signals, Later and dismiss`} onClick={onToggle}
          className={`tap absolute inset-0 rounded-[12px] ${ring}`} />
        <div className="pointer-events-none relative flex min-w-0 flex-1 items-center gap-3">
          <StockIcon symbol={symbol} className="size-8" />
          <span className="min-w-0 flex-1">
            {symbol ? (
              <Link to={stockPath(symbol)} className={`pointer-events-auto block w-fit max-w-full truncate text-[15px] font-bold text-[var(--text)] underline-offset-4 hover:underline rounded-[6px] ${ring}`}>{bareSymbol(symbol)}</Link>
            ) : <span className="block truncate text-[15px] font-bold text-[var(--text)]">{lead.title}</span>}
            {!open && (
              <span className="block text-[13px] leading-snug text-[var(--text-muted)] line-clamp-2">
                {signalText(lead).text}{more > 0 ? ` · +${more} more` : ''}
              </span>
            )}
          </span>
          <ChevronDown className={`w-4 h-4 shrink-0 text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </div>
        {ticket && <span className="relative"><Stamp side={b.primary.label} quantity={lead.action.quantity} onClick={() => onTicket(ticket)} /></span>}
      </div>

      {open && (
        <div className="fade-in pb-4 pl-11 space-y-3">
          {h?.value != null && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] tabular-nums text-[var(--text-muted)]">
              <span className="private font-semibold text-[var(--text)]">{inr(h.value)}</span>
              {h.weight_pct != null && <span className="private">{h.weight_pct.toFixed(1)}% of account</span>}
              {h.pnl != null && <DeltaChip value={h.pnl} pct={h.pnl_pct} suffix="overall" />}
            </div>
          )}
          <ul className="space-y-3">
            {items.map((a) => {
              const s = signalText(a);
              return (
                <li key={a.id} className="flex gap-3">
                  <span aria-hidden="true" className={`mt-[7px] w-2 h-2 shrink-0 rounded-full ${DOT[a.kind] || 'bg-[var(--text-muted)]'}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-1">
                      <p className="min-w-0 flex-1 text-[14px] leading-snug text-[var(--text)]">{s.text}</p>
                      {a.kind === 'bad_news' && (a.action?.news_id || a.action?.url) && <span className="-my-2.5 -mr-2"><ReadLink action={a.action} /></span>}
                    </div>
                    {s.sub && <p className="text-[13px] text-[var(--text-muted)]">{s.sub}</p>}
                    {a.kind === 'bad_news' && <ImpactChips impacts={a.action?.impacts} className="mt-0.5" />}
                    <Note note={notes?.[a.id]} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            {b.primary?.link && to && <Link to={to}><Button variant="secondary">{b.primary.label}</Button></Link>}
            <Button variant="secondary" onClick={() => onAct('snooze', items)} aria-label={`${b.later}: hide for 7 days`}>
              <Clock className="w-4 h-4" aria-hidden="true" />{b.later}
            </Button>
            <Button variant="secondary" onClick={() => onAct('dismiss', items)}>{b.dismiss}</Button>
          </div>
        </div>
      )}
    </li>
  );
};

/** FYI rows (news on what you hold, results and ex-dividend dates, tax dates): folded under the decisions. */
const Fyi = ({ watch, soon, held, notes, onAct }) => {
  const [open, setOpen] = useState(false);
  const n = watch.reduce((k, s) => k + s.items.length, 0) + soon.length;
  if (!n) return null;
  return (
    <div className="border-t border-[var(--border)]">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className={`tap flex w-full items-center gap-3 min-h-12 text-left text-[14px] text-[var(--text-muted)] hover:text-[var(--text)] rounded-[12px] ${ring}`}>
        <span className="flex-1">{n} for your information: news, results, dividends, tax dates</span>
        <ChevronDown className={`w-4 h-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <ul className="fade-in pb-2">
          {watch.flatMap((s) => s.items.map((a) => {
            const h = held[s.symbol];
            return (
              <li key={a.id} className="py-2.5 border-t border-[var(--border)]">
                <div className="flex items-start gap-3">
                  <StockIcon symbol={s.symbol} className="size-7 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <Link to={stockPath(s.symbol)} className={`truncate text-[14px] font-bold text-[var(--text)] hover:underline underline-offset-4 rounded-[6px] ${ring}`}>{bareSymbol(s.symbol)}</Link>
                      {h?.pnl_pct != null && (
                        <span className={`private shrink-0 text-[12px] font-medium tabular-nums ${h.pnl_pct < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>
                          {h.pnl_pct < 0 ? '▼' : '▲'} {Math.abs(h.pnl_pct).toFixed(1)}% overall
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[14px] leading-snug text-[var(--text)]">{signalText(a).text}</p>
                    <ImpactChips impacts={a.action?.impacts} className="mt-0.5" />
                    <Note note={notes?.[a.id]} />
                  </div>
                  <div className="flex shrink-0 -mr-2 -mt-1.5">
                    {(a.action?.news_id || a.action?.url) && <ReadLink action={a.action} />}
                    <IconButton label={`${holdingButtons(a).dismiss}: hide this`} onClick={() => onAct('dismiss', [a])}><Check className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                  </div>
                </div>
              </li>
            );
          }))}
          {soon.map(({ item: a, date, label }) => {
            const d = date && eventDay(date);
            const b = holdingButtons(a);
            const to = rowLink(a);
            return (
              <li key={a.id} className="py-2.5 border-t border-[var(--border)]">
                <div className="flex items-center gap-3">
                  <div className="w-11 shrink-0 rounded-[12px] bg-[var(--surface-2)] py-1 text-center tabular-nums" aria-hidden={d ? 'true' : undefined}>
                    {d ? (
                      <>
                        <div className="text-[12px] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">{d.dow}</div>
                        <div className="text-[15px] font-bold leading-tight text-[var(--text)]">{d.day} <span className="text-[12px] font-medium text-[var(--text-muted)]">{d.month}</span></div>
                      </>
                    ) : <Receipt className="mx-auto my-1.5 w-5 h-5 text-[var(--text-muted)]" aria-hidden="true" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    {label ? (
                      <p className="text-[14px] text-[var(--text)]">
                        {to ? <Link to={to} className="font-semibold hover:underline underline-offset-4">{bareSymbol(a.symbol)}</Link> : <span className="font-semibold">{bareSymbol(a.symbol)}</span>}
                        <span className="text-[var(--text-muted)]"> · {label}</span>
                        {d && <span className="sr-only"> on {d.dow} {d.day} {d.month}</span>}
                      </p>
                    ) : (
                      <p className="text-[14px] font-semibold text-[var(--text)]">{to ? <Link to={to} className="hover:underline underline-offset-4">{a.title}</Link> : a.title}</p>
                    )}
                    {a.detail && <p className="text-[13px] text-[var(--text-muted)]">{a.detail}</p>}
                  </div>
                  <div className="flex shrink-0 -mr-2">
                    <IconButton label={`${b.later}: hide for 7 days`} onClick={() => onAct('snooze', [a])}><Clock className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                    <IconButton label={`${b.dismiss}: hide this`} onClick={() => onAct('dismiss', [a])}><Check className="w-[18px] h-[18px]" aria-hidden="true" /></IconButton>
                  </div>
                </div>
                <Note note={notes?.[a.id]} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

/**
 * Ideas' first lane, "Decide on your holdings": every /mine/actions row about what you own, triaged
 * (`utils/ideas.js::triageHoldings`). One row per stock to act on, its stamp opening the ticket and a tap opening its
 * signals, position, AI note, Later (snooze 7 days) and the row's own dismiss label (`holdingButtons`). News-only
 * stocks and dated rows fold under "for your information".
 */
const HoldingActions = ({ actions, onChanged }) => {
  const [ticket, setTicket] = useState(null);
  const [open, setOpen] = useState(null); // the one stock showing its detail
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

  return (
    <>
      {now.length === 0 ? (
        <p className="py-4 text-[15px] text-[var(--text)]">
          You're clear. <span className="text-[var(--text-muted)]">Exit alerts, verdict changes and adds for what you own show up here.</span>
        </p>
      ) : (
        <ul>
          {now.map((s) => {
            const k = s.symbol || s.items[0].id;
            return (
              <StockRow key={k} stock={s} h={held[s.symbol]} notes={notes} open={open === k}
                onToggle={() => setOpen((o) => (o === k ? null : k))} onAct={act} onTicket={setTicket} />
            );
          })}
        </ul>
      )}
      <Fyi watch={watch} soon={soon} held={held} notes={notes} onAct={act} />
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={onChanged} />}
    </>
  );
};

export default HoldingActions;
