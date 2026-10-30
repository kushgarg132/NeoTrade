import React, { useState } from 'react';
import Button from '../ui/Button';
import api, { endpoints } from '../../utils/api';

/** Stop AI: turns the autopilot off (same call as the old Stop autopilot), after a confirm. */
const StopAi = ({ onStopped, compact = false }) => {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put(endpoints.settings.preferences, { autopilot_enabled: false });
      setAsking(false);
      onStopped?.();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not stop the AI. Try again.');
    } finally {
      setBusy(false);
    }
  };
  if (!asking) return <Button variant="danger" className={compact ? 'shrink-0 px-4 text-[14px]' : ''} onClick={() => setAsking(true)}>Stop AI</Button>;
  return (
    <div role="alertdialog" aria-label="Confirm stop AI" className={`${compact ? 'basis-full' : ''} w-full rounded-[12px] border border-[var(--loss)] p-3 space-y-2`}>
      <p className="text-[15px] text-[var(--text)]">Stop the AI trading? It places no new orders until you turn it on again.</p>
      {error && <p role="alert" className="text-[14px] text-[var(--loss)]">{error}</p>}
      <div className="flex gap-2">
        <Button variant="danger" onClick={stop} disabled={busy} className="flex-1">{busy ? 'Stopping…' : 'Yes, stop'}</Button>
        <Button variant="secondary" onClick={() => setAsking(false)} disabled={busy} className="flex-1">Cancel</Button>
      </div>
    </div>
  );
};

export default StopAi;
