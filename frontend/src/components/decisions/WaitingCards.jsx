import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Sheet } from '../doc/Doc';
import { Badge } from '../common/Badge';
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

const minutesLeft = (iso) => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 60000));

const WaitingCard = ({ card, onSettled }) => {
  const [busy, setBusy] = useState(null);
  const [secondTap, setSecondTap] = useState(false);
  const [note, setNote] = useState(null);

  const confirm = async () => {
    setBusy('confirm');
    setNote(null);
    try {
      const res = await api.post(endpoints.chat.confirm(card.id), { second_tap: secondTap });
      if (res.data.status === 'NEEDS_SECOND_TAP') {
        setSecondTap(true);
      } else {
        setNote(res.data.result);
        setTimeout(onSettled, 1500);
      }
    } catch (err) {
      setNote(detailText(err, 'This card could not be confirmed.'));
      setTimeout(onSettled, 2500);
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
        <Badge variant={card.venue === 'live' ? 'warning' : 'secondary'}>{card.venue === 'live' ? 'Mine' : 'Paper'}</Badge>
        <span className="text-sm flex-1 min-w-0">{card.summary}</span>
        <span className="doc-meta shrink-0">{minutesLeft(card.expires_at)} min left</span>
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
          disabled={busy !== null}
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

  const load = () =>
    api
      .get(endpoints.chat.pending)
      .then((res) => setCards(res.data))
      .catch(() => setCards([]));

  useEffect(() => {
    load();
  }, []);

  const shown = venue ? cards.filter((card) => card.venue === venue) : cards;
  if (shown.length === 0) return null;

  return (
    <Sheet title="Waiting for you" meta={String(shown.length)}>
      <ul className="divide-y divide-[var(--rule)]">
        {shown.map((card) => (
          <WaitingCard key={card.id} card={card} onSettled={load} />
        ))}
      </ul>
    </Sheet>
  );
};

export default WaitingCards;
