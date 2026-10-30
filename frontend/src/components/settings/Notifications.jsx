import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from './Panel';
import TelegramLink from './TelegramLink';
import { Segmented } from './Fields';
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
    <>
    <Sheet title="Telegram">
      <TelegramLink />
    </Sheet>
    <Sheet title="News alerts">
      <div role="group" aria-label="News alerts">
        <p className="text-[13px] text-[var(--text-muted)] mb-2">
          Material news, as a toast here and on Telegram when linked. A market-wide shock reaches anyone holding something.
        </p>
        {value === null ? <Ruling rows={1} /> : (
          <Segmented label="News alerts" options={NEWS_ALERTS} value={value} onChange={pick} />
        )}
        {note && <p role="alert" className="text-[13px] text-[var(--loss)] pt-2">{note}</p>}
      </div>
    </Sheet>
    </>
  );
};

export default Notifications;
