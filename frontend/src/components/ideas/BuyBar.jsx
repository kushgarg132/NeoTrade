import React, { useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import Button from '../ui/Button';
import Countdown from '../common/Countdown';
import api, { endpoints } from '../../utils/api';
import { tokenRefusal, deadlineFrom, EXPIRED_NOTE } from '../../utils/liveConfirm';
import { bareSymbol } from '../../utils/formatters';
import { inr } from '../ui/format';

/**
 * Buy / Skip for one pending suggestion. Buy is real money on the user's own
 * account and keeps the server's second tap: the first call returns a one-time
 * token, the second sends it (armed 600 ms after it appears).
 */
const BuyBar = ({ idea, id, onDone }) => {
  const [busy, setBusy] = useState(null);
  const [failure, setFailure] = useState(null);
  const [armed, setArmed] = useState(false); // first tap done, token held
  const token = useRef(null);
  const armedAt = useRef(0);
  const [until, setUntil] = useState(0);

  const back = () => { token.current = null; setArmed(false); };
  const detail = (err, fallback) => err?.response?.data?.detail && typeof err.response.data.detail === 'string' ? err.response.data.detail : fallback;

  const buy = async () => {
    if (armed && Date.now() < armedAt.current) return;
    setBusy('buy');
    setFailure(null);
    try {
      const res = await api.post(endpoints.suggestions.approveLive(id), { confirm_token: token.current || undefined });
      if (!armed) {
        token.current = res.data.confirm_token;
        setUntil(deadlineFrom(res.data.expires_in));
        armedAt.current = Date.now() + 600;
        setArmed(true);
      } else {
        back();
        onDone();
      }
    } catch (err) {
      const refusal = armed && tokenRefusal(err);
      back();
      setFailure(refusal || detail(err, 'Could not place the order'));
    } finally {
      setBusy(null);
    }
  };

  const skip = async () => {
    if (armed) return back();
    setBusy('skip');
    setFailure(null);
    try {
      await api.post(endpoints.suggestions.reject(id), {});
      onDone();
    } catch (err) {
      setFailure(detail(err, 'Could not record the decision'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-2">
      {armed && (
        <p role="alert" className="text-[14px] text-[var(--loss)]">
          Real money: {idea.side === 'SELL' ? 'sells' : 'buys'} {idea.qty} {bareSymbol(idea.symbol)} at market on your account
          {idea.risk != null && <>, risking <span className="private"><span className="figure-md">{inr(idea.risk)}</span></span></>}. Tap again to send.{' '}
          <Countdown until={until} onExpire={() => { back(); setFailure(EXPIRED_NOTE); }} />
        </p>
      )}
      {failure && <p role="alert" className="text-[14px] text-[var(--loss)]">{failure}</p>}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" onClick={skip} disabled={busy !== null}>
          {busy === 'skip' && <Loader2 className="w-4 h-4 animate-spin" />}{armed ? 'Cancel' : 'Skip'}
        </Button>
        <Button variant={armed ? 'danger' : 'primary'} onClick={buy} disabled={busy !== null}>
          {busy === 'buy' && <Loader2 className="w-4 h-4 animate-spin" />}
          {armed ? 'Send real order' : idea.side === 'SELL' ? 'Sell…' : 'Buy…'}
        </Button>
      </div>
    </div>
  );
};

export default BuyBar;
