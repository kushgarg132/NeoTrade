import React, { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, X } from 'lucide-react';
import { Button } from '../common/Button';
import api, { endpoints } from '../../utils/api';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * The order ticket: Buy or Sell, on Paper (the practice book) or Mine (the
 * user's own broker account), market or limit. Review stores the same order
 * card the chat makes, after the same checks; Confirm runs it through
 * /chat/actions, and real money needs a second tap. The AI account is not
 * an option here. Closing after Review cancels the card so it does not sit
 * in Today's "Needs you".
 */

const detailText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

const Segmented = ({ label, options, value, onChange, disabled = {}, locked = false }) => (
  <div role="radiogroup" aria-label={label} className="flex border border-[var(--rule-strong)]">
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
            'flex-1 min-h-11 sm:min-h-9 px-2 text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
            '[&:not(:first-child)]:border-l border-[var(--rule-strong)]',
            selected ? option.selectedClass || 'bg-[var(--ink)] text-[var(--paper)]' : 'bg-[var(--paper)] text-[var(--ink-soft)] hover:text-[var(--ink)]'
          )}
        >
          {option.label}
        </button>
      );
    })}
  </div>
);

const OrderTicket = ({ symbol, side: initialSide = 'BUY', venue: initialVenue = 'paper', lastPrice, onClose, onDone }) => {
  const titleId = useId();
  const dialogRef = useRef(null);
  const [side, setSide] = useState(initialSide);
  const [venue, setVenue] = useState(initialVenue);
  const [product, setProduct] = useState('CNC');
  const [orderType, setOrderType] = useState('MARKET');
  const [limitPrice, setLimitPrice] = useState(lastPrice ? String(lastPrice) : '');
  const [quantity, setQuantity] = useState('1');
  const [hasMine, setHasMine] = useState(null);
  const [card, setCard] = useState(null);
  const [needsSecondTap, setNeedsSecondTap] = useState(false);
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
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        const mine = Object.values(res.data.broker_roles || {}).includes('mine');
        setHasMine(mine);
        if (!mine) setVenue('paper');
      })
      .catch(() => {
        setHasMine(false);
        setVenue('paper');
      });
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
    return () => document.removeEventListener('keydown', onKey);
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
    setNeedsSecondTap(false);
    setError(null);
  };

  const review = async () => {
    const request = ++requestRef.current;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post(endpoints.orders.propose, {
        symbol, side, quantity: qty, product, order_type: orderType,
        limit_price: orderType === 'LIMIT' ? limit : null, venue: venue === 'mine' ? 'live' : 'paper',
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
      const res = await api.post(endpoints.chat.confirm(card.id), { second_tap: needsSecondTap });
      if (res.data.status === 'NEEDS_SECOND_TAP') {
        setNeedsSecondTap(true);
        setArming(true);
        setTimeout(() => setArming(false), 600);
      } else {
        setResult(res.data.result);
        onDone?.();
      }
    } catch (err) {
      // No response at all: the order may be placed. Never say it was not.
      setError(err?.response ? detailText(err, 'The order was not placed.') : 'No answer from the server. The order may have gone through: check Trades before trying again.');
      setCard(null);
      setNeedsSecondTap(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center">
      <div className="absolute inset-0 bg-[var(--ink)]/40" onClick={close} aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full sm:max-w-md sheet bg-[var(--paper)] p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] space-y-3 max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-baseline justify-between gap-3">
          <h2 id={titleId} className="figure-md text-lg">
            {side === 'BUY' ? 'Buy' : 'Sell'} {symbol}
          </h2>
          {lastPrice != null && <span className="doc-meta">Last {formatCurrency(lastPrice)}</span>}
          <button
            type="button"
            onClick={close}
            disabled={busy}
            aria-label="Close the order ticket"
            className="ml-auto inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-8 sm:min-w-8 -my-2 -mr-2 text-[var(--ink-soft)] hover:text-[var(--ink)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {result ? (
          <>
            <p role="status" className="text-sm">{result}</p>
            <Button variant="secondary" className="w-full" onClick={onClose}>Done</Button>
          </>
        ) : (
          <>
            <Segmented
              label="Side"
              value={side}
              onChange={edit(setSide)}
              locked={busy}
              options={[
                { id: 'BUY', label: 'Buy', selectedClass: 'bg-[var(--gain)] text-white' },
                { id: 'SELL', label: 'Sell', selectedClass: 'bg-[var(--loss)] text-[var(--paper)]' },
              ]}
            />
            <Segmented
              label="Account"
              value={venue}
              onChange={edit(setVenue)}
              locked={busy}
              disabled={{ mine: !hasMine }}
              options={[
                { id: 'paper', label: 'Paper' },
                { id: 'mine', label: 'Mine' },
              ]}
            />
            {hasMine === false && (
              <p className="doc-meta normal-case">
                <Link to="/settings?tab=accounts" className="underline" onClick={close}>
                  Connect your broker and set it as My account in Settings
                </Link>{' '}
                to trade it from here.
              </p>
            )}
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

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="field-label block mb-1">Quantity</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  step="1"
                  value={quantity}
                  onChange={(e) => edit(setQuantity)(e.target.value)}
                  disabled={busy}
                  className="w-full bg-transparent border-0 border-b-2 border-[var(--rule-strong)] focus:border-[var(--stamp)] focus:ring-0 py-2 figure-md"
                />
              </label>
              {orderType === 'LIMIT' && (
                <label className="block">
                  <span className="field-label block mb-1">Limit price ₹</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0.05"
                    step="0.05"
                    value={limitPrice}
                    onChange={(e) => edit(setLimitPrice)(e.target.value)}
                    disabled={busy}
                    className="w-full bg-transparent border-0 border-b-2 border-[var(--rule-strong)] focus:border-[var(--stamp)] focus:ring-0 py-2 figure-md"
                  />
                </label>
              )}
            </div>
            {estimate != null && <p className="doc-meta normal-case">About {formatCurrency(estimate)}</p>}

            {card && <p className="text-sm border border-[var(--rule-strong)] bg-[var(--paper-sunk)] px-3 py-2">{card.summary}</p>}
            {error && (
              <p role="alert" className="text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2">
                {error}
              </p>
            )}

            {!card ? (
              <Button className="w-full" onClick={review} disabled={!valid || busy || hasMine === null}>
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Review
              </Button>
            ) : (
              <Button
                className={cn('w-full', needsSecondTap && 'bg-[var(--stamp)] border-[var(--stamp)]')}
                onClick={confirm}
                disabled={busy || arming}
              >
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {needsSecondTap ? 'Real money. Tap Confirm again' : 'Confirm'}
              </Button>
            )}
          </>
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
        ? 'border-[var(--gain)] text-[var(--gain)] hover:bg-[var(--gain-wash)]'
        : 'border-[var(--loss)] text-[var(--loss)] hover:bg-[var(--loss-wash)]'
    )}
  >
    {label}
  </button>
);

export default OrderTicket;
