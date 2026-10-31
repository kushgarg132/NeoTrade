import React, { useState } from 'react';
import Button from '../ui/Button';
import OrderTicket from '../trading/OrderTicket';
import api, { endpoints } from '../../utils/api';
import { parseIdeaId } from '../../utils/ideas';

/** A pick's own actions: Skip hides it from the list (`POST /picks/{id}/dismiss`); Buy opens the order ticket at the
 *  pick's entry, limited to the top of its entry zone (real money keeps the ticket's second tap). */
const PickBar = ({ idea, onDone }) => {
  const [ticket, setTicket] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const skip = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await api.post(endpoints.picks.dismiss(parseIdeaId(idea.id).key));
      onDone();
    } catch {
      setFailure('Could not skip this pick');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2">
      {failure && <p role="alert" className="text-[14px] text-[var(--loss)]">{failure}</p>}
      <div className="flex gap-2">
        <Button variant="secondary" className="px-6" onClick={skip} disabled={busy}>Skip</Button>
        <Button className="flex-1" onClick={() => setTicket(true)} disabled={busy}>Buy</Button>
      </div>
      {ticket && <OrderTicket symbol={idea.symbol} side="BUY" lastPrice={idea.entry} limitPrice={idea.entryZone?.[1]} onClose={() => setTicket(false)} onDone={onDone} />}
    </div>
  );
};

export default PickBar;
