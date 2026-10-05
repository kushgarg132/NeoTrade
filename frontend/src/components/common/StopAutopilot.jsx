import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import api, { endpoints } from '../../utils/api';

/**
 * The autopilot's off switch. Says when it is working, when it failed, and
 * when it stopped; a failed stop is never silent.
 */
const StopAutopilot = ({ on, label = 'Stop', onStopped }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [stoppedAt, setStoppedAt] = useState(null);

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put(endpoints.settings.preferences, { autopilot_enabled: false });
      setStoppedAt(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }));
      onStopped?.();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not stop the autopilot. Try again.');
    } finally {
      setBusy(false);
    }
  };

  if (stoppedAt && !on) return <span className="doc-meta normal-case">Stopped at {stoppedAt}</span>;
  if (!on) return null;
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={stop}
        disabled={busy}
        className="inline-flex items-center gap-1 min-h-11 px-3 text-xs border border-[var(--loss)] text-[var(--loss)] disabled:opacity-60"
      >
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        🛑 {label}
      </button>
      {error && <span role="alert" className="text-xs text-[var(--loss)]">{error}</span>}
    </span>
  );
};

export default StopAutopilot;
