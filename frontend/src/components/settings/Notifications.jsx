import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from './Panel';
import TelegramLink from './TelegramLink';
import { NEWS_ALERTS } from '../../utils/settings';
import api, { endpoints, getPreferences } from '../../utils/api';

const Notifications = () => {
  const [value, setValue] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => {
    getPreferences()
      .then((res) => setValue(res.data?.news_alerts || 'held'))
      .catch(() => setValue('held'));
  }, []);

  const pick = (id) => {
    if (id === value) return;
    const prev = value;
    setValue(id);
    setNote(null);
    api.put(endpoints.settings.preferences, { news_alerts: id }).catch((err) => {
      setValue(prev);
      setNote(err?.response?.data?.detail || 'That value was not saved.');
    });
  };

  return (
    <Sheet title="Telegram and news">
      <TelegramLink />
      <div role="group" aria-label="News alerts" className="py-2">
        <p className="text-[13px] font-medium text-[var(--text-muted)]">News alerts</p>
        <p className="text-[13px] text-[var(--text-muted)] mb-2">
          Material news, as a toast here and on Telegram when linked. A market-wide shock reaches anyone holding something.
        </p>
        {value === null ? <Ruling rows={1} /> : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
            {NEWS_ALERTS.map(([id, label]) => (
              <button key={id} type="button" aria-pressed={id === value} onClick={() => pick(id)}
                className={`min-h-11 rounded-[8px] px-3 text-[14px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                  id === value ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-muted)]'}`}>
                {label}
              </button>
            ))}
          </div>
        )}
        {note && <p role="alert" className="text-[13px] text-[var(--text-muted)] pt-2">{note}</p>}
      </div>
    </Sheet>
  );
};

export default Notifications;
