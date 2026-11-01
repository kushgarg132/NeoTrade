import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from './Panel';
import TelegramLink from './TelegramLink';
import { Row, Segmented, Toggle } from './Fields';
import { NEWS_ALERTS } from '../../utils/settings';
import api, { endpoints, getPreferences } from '../../utils/api';

const INSTANT = [['exit', 'Exit and sell signals'], ['money', 'Money moved'], ['news_breaking', 'Breaking news on holdings'], ['action', 'Needs your action']];
const DIGEST = [['ideas', 'New ideas'], ['stale_ideas', 'Expiring ideas'], ['news', 'Other news'], ['learning', 'Strategy learning'], ['review', 'Weekly review'], ['autopilot_refused', 'Autopilot refusals']];
const IMPACT = [5, 6, 7, 8, 9].map((n) => [n, `${n}/10`]);

const Notifications = () => {
  const [value, setValue] = useState(null);
  const [mute, setMute] = useState({});
  const [minImpact, setMinImpact] = useState(7);
  const [note, setNote] = useState(null);

  useEffect(() => {
    getPreferences()
      .then((res) => {
        setValue(res.data?.news_alerts || 'held');
        setMute(res.data?.alert_mute || {});
        setMinImpact(res.data?.breaking_news_min ?? 7);
      })
      .catch(() => setValue('held'));
  }, []);

  // PUT one field; on error put the old value back and show the note in the sheet `at`.
  const save = (body, revert, at) => {
    setNote(null);
    api.put(endpoints.settings.preferences, body).catch((err) => {
      revert();
      setNote({ at, text: err?.response?.data?.detail || 'That value was not saved.' });
    });
  };

  const flip = (kind, at) => {
    const prev = mute;
    const next = { ...mute, [kind]: !mute[kind] };
    setMute(next);
    save({ alert_mute: next }, () => setMute(prev), at);
  };

  const pickImpact = (n) => {
    if (n === minImpact) return;
    const prev = minImpact;
    setMinImpact(n);
    save({ breaking_news_min: n }, () => setMinImpact(prev), 'impact');
  };

  const noteAt = (at) => note?.at === at && <p role="alert" className="text-[13px] text-[var(--loss)] pt-2">{note.text}</p>;

  const kindRows = (list, at) => list.map(([kind, label]) => (
    <Row key={kind} label={label}>
      <Toggle on={!mute[kind]} label={label} onClick={() => flip(kind, at)} />
    </Row>
  ));

  const pick = (id) => {
    if (id === value) return;
    const prev = value;
    setValue(id);
    save({ news_alerts: id }, () => setValue(prev), 'news');
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
        {noteAt('news')}
      </div>
    </Sheet>
    <Sheet title="Instant">{kindRows(INSTANT, 'instant')}{noteAt('instant')}</Sheet>
    <Sheet title="In the digest">{kindRows(DIGEST, 'digest')}{noteAt('digest')}</Sheet>
    <Sheet title="Breaking news threshold">
      <Row label="Breaking news from impact">
        <Segmented label="Breaking news from impact" options={IMPACT} value={minImpact} onChange={pickImpact} />
      </Row>
      {noteAt('impact')}
    </Sheet>
    </>
  );
};

export default Notifications;
