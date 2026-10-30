import React, { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Loader2, Minus, Plus, X } from 'lucide-react';
import Button from '../ui/Button';
import Badge from '../ui/Badge';
import { inr, pct } from '../ui/format';
import { px } from '../ideas/levels';
import api, { endpoints, getPreferences } from '../../utils/api';
import { cn } from '../../utils/cn';
import Countdown from '../common/Countdown';
import { tokenRefusal, deadlineFrom, EXPIRED_NOTE } from '../../utils/liveConfirm';

/**
 * The order ticket: Buy or Sell, on Mine (the user's own broker
 * account, real money), market or limit. Review stores the same order
 * card the chat makes, after the same checks; Confirm runs it through
 * /chat/actions, and real money needs a second tap. The AI account is not
 * an option here. Closing after Review cancels the card so it does not sit
 * in Today's "Needs you".
 */

const detailText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

/** A pill switch: track in surface-2, the chosen option filled (`selectedClass`, else text on surface). */
const Segmented = ({ label, options, value, onChange, disabled = {}, locked = false, size = 'md' }) => (
  <div role="radiogroup" aria-label={label} className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
    {options.map((option) => {
      const selected = option.id === value;
      return (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={selected}
          disabled={locked || disabled[option.id]}
          onClick={() => onChange(option.id)}
          className={cn(
            'tap flex-1 rounded-[9px] px-2 font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]',
            size === 'lg' ? 'min-h-11 text-[15px]' : 'min-h-9 text-[13px]',
            selected ? option.selectedClass || 'bg-[var(--text)] text-[var(--surface)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'
          )}
        >
          {option.label}
        </button>
      );
    })}
  </div>
);

const Stepper = ({ value, onChange, disabled }) => {
  const n = parseInt(value, 10) || 0;
  const step = (d) => onChange(String(Math.max(1, n + d)));
  const btn = 'tap inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';
  return (
    <div className="flex items-center gap-2">
      <button type="button" className={btn} onClick={() => step(-1)} disabled={disabled || n <= 1} aria-label="One share fewer"><Minus className="w-4 h-4" aria-hidden="true" /></button>
      <input
        type="number" inputMode="numeric" min="1" step="1" aria-label="Quantity"
        value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}
        className="w-full min-w-0 bg-transparent border-0 p-0 text-center text-[28px] font-bold tracking-[-0.02em] tabular-nums text-[var(--text)] focus:ring-0 focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <button type="button" className={btn} onClick={() => step(1)} disabled={disabled} aria-label="One share more"><Plus className="w-4 h-4" aria-hidden="true" /></button>
    </div>
  );
};

// Your own account only: the AI account's paper book is the AI's to trade.
const OrderTicket = ({ symbol, side: initialSide = 'BUY', lastPrice, quantity: initialQuantity, limitPrice: initialLimit, onClose, onDone }) => {
  const titleId = useId();
  const dialogRef = useRef(null);
  const [side, setSide] = useState(initialSide);
  const [product, setProduct] = useState('CNC');
  // A suggested trade arrives pre-filled: its quantity, and a limit at its price.
  const [orderType, setOrderType] = useState(initialLimit ? 'LIMIT' : 'MARKET');
  const [limitPrice, setLimitPrice] = useState(String(initialLimit ?? lastPrice ?? ''));
  const [quantity, setQuantity] = useState(String(initialQuantity ?? 1));
  const [hasMine, setHasMine] = useState(null);
  const [card, setCard] = useState(null);
  const [confirmToken, setConfirmToken] = useState(null); // set by the first tap on real money
  const [until, setUntil] = useState(0);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  busyRef.current = busy;
  // The real-money button arms 600ms after it appears, so one fast double
  // tap on Confirm cannot send both taps.
  const [arming, setArming] = useState(false);
  const [error, setError] = useState(null);
  const cardRef = useRef(null);
  cardRef.current = result ? null : card;
  const requestRef = useRef(0);

  useEffect(() => {
    getPreferences()
      .then((res) => {
        const mine = Object.values(res.data.broker_roles || {}).includes('mine');
        setHasMine(mine);
      })
      .catch(() => setHasMine(false));
  }, []);

  // A reviewed card the user walked away from is cancelled, never left live.
  const cancelCard = () => {
    if (cardRef.current) api.post(endpoints.chat.cancel(cardRef.current.id)).catch(() => {});
    cardRef.current = null;
  };

  // Not while a request is in flight: the order may already be on its way.
  const close = () => {
    if (busyRef.current) return;
    cancelCard();
    onClose();
  };

  // Unmounted any other way (Back, a route change): the card still goes.
  useEffect(() => cancelCard, []);

  useEffect(() => {
    const opener = document.activeElement; // focus goes back here on close
    const dialog = dialogRef.current;
    dialog?.querySelector('button, input')?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') close();
      if (event.key === 'Tab' && dialog) {
        const focusable = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), a[href]')];
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      opener?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const qty = parseInt(quantity, 10);
  const limit = parseFloat(limitPrice);
  const basis = orderType === 'LIMIT' ? limit : lastPrice;
  const estimate = qty > 0 && basis > 0 ? qty * basis : null;
  const valid = qty > 0 && (orderType === 'MARKET' || limit > 0);

  const edit = (setter) => (value) => {
    requestRef.current += 1; // a Review still in flight is now for old values
    setter(value);
    if (card) api.post(endpoints.chat.cancel(card.id)).catch(() => {});
    setCard(null);
    setConfirmToken(null);
    setError(null);
  };

  const review = async () => {
    const request = ++requestRef.current;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post(endpoints.orders.propose, {
        symbol, side, quantity: qty, product, order_type: orderType,
        limit_price: orderType === 'LIMIT' ? limit : null, venue: 'live',
      });
      if (request !== requestRef.current) {
        api.post(endpoints.chat.cancel(res.data.id)).catch(() => {});
        return;
      }
      setCard(res.data);
    } catch (err) {
      if (request === requestRef.current) setError(detailText(err, 'Could not check this order.'));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post(endpoints.chat.confirm(card.id), { confirm_token: confirmToken });
      if (res.data.status === 'NEEDS_SECOND_TAP') {
        setConfirmToken(res.data.confirm_token);
        setUntil(deadlineFrom(res.data.expires_in));
        setArming(true);
        setTimeout(() => setArming(false), 600);
      } else {
        setResult(res.data.result);
        onDone?.();
      }
    } catch (err) {
      // A refused token leaves the card PROPOSED on the server: keep it, back to the first tap.
      const refusal = confirmToken && tokenRefusal(err);
      if (refusal) {
        setConfirmToken(null);
        setError(refusal);
        return;
      }
      // No response at all: the order may be placed. Never say it was not.
      setError(err?.response ? detailText(err, 'The order was not placed.') : 'No answer from the server. The order may have gone through: check Journal before trying again.');
      setCard(null);
      setConfirmToken(null);
    } finally {
      setBusy(false);
    }
  };

  const buy = side === 'BUY';
  const verb = buy ? 'Buy' : 'Sell';
  const vsLast = orderType === 'LIMIT' && limit > 0 && lastPrice > 0 ? limit / lastPrice - 1 : null;

  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="fade-in relative w-full sm:max-w-md rounded-t-[28px] sm:rounded-[28px] border border-[var(--border)] bg-[var(--surface)] px-5 pt-3 sm:pt-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] max-h-[92vh] overflow-y-auto"
      >
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-[var(--border)] sm:hidden" aria-hidden="true" />
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-[22px] font-bold tracking-[-0.02em] text-[var(--text)] truncate">
              {verb} {symbol}
            </h2>
            <p className="text-[13px] text-[var(--text-muted)] tabular-nums">
              {lastPrice != null ? `Last ${px(lastPrice)} · ` : ''}Your own account
            </p>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={busy}
            aria-label="Close the order ticket"
            className="tap -mr-2 -mt-1 inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {result ? (
          <div className="mt-5 space-y-4">
            <div role="status" className="flex gap-3 rounded-[20px] bg-[var(--surface-2)] p-4">
              <span className="inline-flex w-8 h-8 shrink-0 items-center justify-center rounded-full bg-[var(--gain-soft)] text-[var(--gain)]"><Check className="w-4 h-4" aria-hidden="true" /></span>
              <p className="text-[15px] text-[var(--text)]">{result}</p>
            </div>
            <Button variant="secondary" className="w-full" onClick={onClose}>Done</Button>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <Segmented
              label="Side"
              size="lg"
              value={side}
              onChange={edit(setSide)}
              locked={busy}
              options={[
                { id: 'BUY', label: 'Buy', selectedClass: 'bg-[var(--gain)] text-[var(--accent-ink)]' },
                { id: 'SELL', label: 'Sell', selectedClass: 'bg-[var(--loss)] text-[var(--accent-ink)]' },
              ]}
            />
            {hasMine === false && (
              <p className="rounded-[12px] bg-[var(--surface-2)] px-3 py-2 text-[14px] text-[var(--text)]">
                <Link to="/settings/brokers" className="font-semibold text-[var(--accent)] underline underline-offset-4" onClick={close}>
                  Connect your broker and set it as My account in Settings
                </Link>{' '}
                to trade it from here.
              </p>
            )}

            <div className="rounded-[20px] bg-[var(--surface-2)] p-4 space-y-4">
              <div>
                <div className="mb-2 text-[13px] font-semibold text-[var(--text-muted)]">Shares</div>
                <Stepper value={quantity} onChange={edit(setQuantity)} disabled={busy} />
              </div>
              <div className="border-t border-[var(--border)] pt-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-[13px] font-semibold text-[var(--text-muted)]">Price</span>
                  <div className="w-44">
                    <Segmented
                      label="Order type"
                      value={orderType}
                      onChange={edit(setOrderType)}
                      locked={busy}
                      options={[
                        { id: 'MARKET', label: 'Market' },
                        { id: 'LIMIT', label: 'Limit' },
                      ]}
                    />
                  </div>
                </div>
                {orderType === 'LIMIT' ? (
                  <label className="flex items-center gap-2 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 focus-within:ring-2 focus-within:ring-[var(--accent)]">
                    <span className="text-[17px] font-semibold text-[var(--text-muted)]">₹</span>
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0.05"
                      step="0.05"
                      aria-label="Limit price in rupees"
                      value={limitPrice}
                      onChange={(e) => edit(setLimitPrice)(e.target.value)}
                      disabled={busy}
                      className="min-h-12 w-full min-w-0 bg-transparent border-0 p-0 text-[20px] font-bold tabular-nums text-[var(--text)] focus:ring-0 focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    {vsLast != null && Math.abs(vsLast) >= 0.0005 && (
                      <span className="shrink-0 text-[12px] font-medium tabular-nums text-[var(--text-muted)]">
                        {pct(Math.abs(vsLast), { dp: 1 })} {vsLast > 0 ? 'above' : 'below'} last
                      </span>
                    )}
                  </label>
                ) : (
                  <p className="text-[15px] text-[var(--text)]">At the market price{lastPrice != null ? <span className="text-[var(--text-muted)] tabular-nums">, last {px(lastPrice)}</span> : ''}</p>
                )}
              </div>
              <div className="border-t border-[var(--border)] pt-4 flex items-center justify-between gap-3">
                <span className="text-[13px] font-semibold text-[var(--text-muted)]">Hold as</span>
                <div className="w-44">
                  <Segmented
                    label="Product"
                    value={product}
                    onChange={edit(setProduct)}
                    locked={busy}
                    options={[
                      { id: 'CNC', label: 'Delivery' },
                      { id: 'MIS', label: 'Intraday' },
                    ]}
                  />
                </div>
              </div>
            </div>

            <div className="flex items-end justify-between gap-3 px-1">
              <span className="text-[13px] font-semibold text-[var(--text-muted)]">Order value</span>
              <span className="private text-[28px] font-extrabold leading-none tracking-[-0.03em] tabular-nums text-[var(--text)]">
                {estimate != null ? `≈ ${inr(estimate)}` : '—'}
              </span>
            </div>

            {card && (
              <div className="flex gap-3 rounded-[16px] border border-[var(--border)] px-3 py-3">
                <Check className="w-4 h-4 mt-0.5 shrink-0 text-[var(--gain)]" aria-hidden="true" />
                <p className="text-[14px] leading-snug text-[var(--text)]">{card.summary}</p>
              </div>
            )}
            {error && (
              <p role="alert" className="rounded-[12px] bg-[var(--loss-soft)] px-3 py-2 text-[14px] text-[var(--loss)]">
                {error}
              </p>
            )}

            {!card ? (
              <Button className="w-full min-h-12 text-[16px]" onClick={review} disabled={!valid || busy || !hasMine}>
                {busy && <Loader2 className="w-4 h-4 animate-spin" />}
                Review order
              </Button>
            ) : (
              <div className="space-y-2">
                {confirmToken && (
                  <div className="flex items-center justify-center gap-2 text-[13px] text-[var(--text-muted)]">
                    <Badge kind="live">Real money</Badge>
                    <Countdown until={until} onExpire={() => { setConfirmToken(null); setError(EXPIRED_NOTE); }} />
                  </div>
                )}
                <Button
                  variant={buy ? 'gain' : 'danger'}
                  className={cn('w-full min-h-12 text-[16px]', confirmToken && 'ring-2 ring-offset-2 ring-offset-[var(--surface)] ring-[var(--warn)]')}
                  onClick={confirm}
                  disabled={busy || arming}
                >
                  {busy && <Loader2 className="w-4 h-4 animate-spin" />}
                  {confirmToken ? `Tap again to ${verb.toLowerCase()} · real money` : `Confirm: ${verb.toLowerCase()} ${qty || ''} ${symbol}`}
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/** A compact Buy/Sell/Add button for table rows; never opens the row. */
export const TicketButton = ({ label, tone = 'gain', onClick }) => (
  <button
    type="button"
    onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}
    className={cn(
      'min-h-11 sm:min-h-0 px-2 py-1 text-xs font-semibold border transition-colors',
      tone === 'gain'
        ? 'border-[var(--gain)] text-[var(--gain)] hover:bg-[var(--gain-soft)]'
        : 'border-[var(--loss)] text-[var(--loss)] hover:bg-[var(--loss-soft)]'
    )}
  >
    {label}
  </button>
);

export default OrderTicket;
