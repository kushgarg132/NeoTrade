import React, { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Sheet } from '../doc/Doc';
import MoneyBadge from '../common/MoneyBadge';
import { Button } from '../common/Button';
import api, { endpoints } from '../../utils/api';

/**
 * Cards from the chat or the order ticket that wait for a Confirm. A card on
 * the user's own account needs a second tap, enforced by the server.
 * `venue` filters to 'paper' or 'live'; null shows both.
 */
const detailText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

const minutesLeft = (iso, now) => Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 60000));

const WaitingCard = ({ card, now, onSettled }) => {
  const [busy, setBusy] = useState(null);
  const [secondTap, setSecondTap] = useState(false);
  const [note, setNote] = useState(null);
  // The real-money tap arms 600ms after it appears: one double tap is not two taps.
  const [arming, setArming] = useState(false);
  const timers = useRef([]);
  const later = (fn, ms) => timers.current.push(setTimeout(fn, ms));
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const confirm = async () => {
    setBusy('confirm');
    setNote(null);
    try {
      const res = await api.post(endpoints.chat.confirm(card.id), { second_tap: secondTap });
      if (res.data.status === 'NEEDS_SECOND_TAP') {
        setSecondTap(true);
        setArming(true);
        later(() => setArming(false), 600);
      } else {
        setNote(res.data.result);
        later(onSettled, 1500);
      }
    } catch (err) {
      setNote(err?.response ? detailText(err, 'This card could not be confirmed.') : 'No answer from the server. The order may have gone through: check Trades before trying again.');
      later(onSettled, 2500);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    setBusy('cancel');
    await api.post(endpoints.chat.cancel(card.id)).catch(() => {});
    onSettled();
  };

  return (
    <li className="py-3 space-y-2">
      <div className="flex items-baseline gap-2">
        <MoneyBadge kind={card.venue === 'live' ? 'mine' : 'paper'} />
        <span className="text-sm flex-1 min-w-0">{card.summary}</span>
        <span className="doc-meta shrink-0">{minutesLeft(card.expires_at, now)} min left</span>
      </div>
      {note && <p role="status" className="text-sm text-[var(--ink-soft)]">{note}</p>}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" onClick={cancel} disabled={busy !== null}>
          {busy === 'cancel' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={confirm}
          disabled={busy !== null || arming}
          className={secondTap ? 'bg-[var(--stamp)] border-[var(--stamp)]' : undefined}
        >
          {busy === 'confirm' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {secondTap ? 'Real money. Tap Confirm again' : 'Confirm'}
        </Button>
      </div>
    </li>
  );
};

const WaitingCards = ({ venue }) => {
  const [cards, setCards] = useState([]);
  // Re-rendered every 30s so "min left" counts down; expired cards drop out.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(tick);
  }, []);

  const load = () =>
    api
      .get(endpoints.chat.pending)
      .then((res) => setCards(res.data))
      .catch(() => setCards([]));

  useEffect(() => {
    load();
  }, []);

  const shown = (venue ? cards.filter((card) => card.venue === venue) : cards)
    .filter((card) => minutesLeft(card.expires_at, now) > 0);
  if (shown.length === 0) return null;

  return (
    <Sheet title="Waiting for you" meta={String(shown.length)}>
      <ul className="divide-y divide-[var(--rule)]">
        {shown.map((card) => (
          <WaitingCard key={card.id} card={card} now={now} onSettled={load} />
        ))}
      </ul>
    </Sheet>
  );
};

export default WaitingCards;
