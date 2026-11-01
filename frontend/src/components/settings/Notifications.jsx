import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from './Panel';
import TelegramLink from './TelegramLink';
import { Row, Segmented, Toggle } from './Fields';
import { NEWS_ALERTS } from '../../utils/settings';
import { flipMute, undoMute } from '../../utils/alertMute';
import { detailToText } from '../../utils/errors';
import api, { endpoints, getPreferences } from '../../utils/api';

const INSTANT = [['exit', 'Exit and sell signals'], ['money', 'Money moved'], ['news_breaking', 'Breaking news on holdings'], ['action', 'Needs your action']];
const DIGEST = [['ideas', 'New ideas'], ['stale_ideas', 'Expiring ideas'], ['news', 'Other news'], ['learning', 'Strategy learning'], ['review', 'Weekly review'], ['autopilot_refused', 'Autopilot refusals']];
const IMPACT = [5, 6, 7, 8, 9].map((n) => [n, `${n}/10`]);

const Notifications = () => {
  const [value, setValue] = useState(null);
  const [mute, setMute] = useState({});
  const [loaded, setLoaded] = useState(null); // null loading, true ok, false failed: no controls, so no PUT can erase stored mutes
  const [busy, setBusy] = useState(false); // one save in flight; the toggles wait for it
  const [minImpact, setMinImpact] = useState(7);
  const [note, setNote] = useState(null);

  useEffect(() => {
    getPreferences()
      .then((res) => {
        setValue(res.data?.news_alerts || 'held');
        setMute(res.data?.alert_mute || {});
        setMinImpact(res.data?.breaking_news_min ?? 7);
        setLoaded(true);
      })
      .catch(() => {
        setValue('held');
        setLoaded(false);
        setNote({ at: 'news', text: 'Alert settings did not load. Reload to change them.' });
      });
  }, []);

  // PUT one field; on error put the old value back and show the note in the sheet `at`.
  const save = (body, revert, at) => {
    setNote(null);
    setBusy(true);
    api.put(endpoints.settings.preferences, body).catch((err) => {
      revert();
      setNote({ at, text: detailToText(err?.response?.data?.detail) || 'That value was not saved.' });
    }).finally(() => setBusy(false));
  };

  const flip = (kind, at) => {
    const was = Boolean(mute[kind]);
    const next = flipMute(mute, kind);
    setMute(next);
    save({ alert_mute: next }, () => setMute((m) => undoMute(m, kind, was)), at);
  };

  const pickImpact = (n) => {
    if (n === minImpact) return;
    const prev = minImpact;
    setMinImpact(n);
    save({ breaking_news_min: n }, () => setMinImpact(prev), 'impact');
  };

  const noteAt = (at) => note?.at === at && <p role="alert" className="text-[13px] text-[var(--loss)] pt-2">{note.text}</p>;

  const gate = (_at, children) => (loaded === null ? <Ruling rows={1} /> : loaded ? children : null);

  const kindRows = (list, at) => list.map(([kind, label]) => (
    <Row key={kind} label={label}>
      <Toggle on={!mute[kind]} label={label} disabled={busy} onClick={() => flip(kind, at)} />
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
        {gate('news', (
          <Segmented label="News alerts" options={NEWS_ALERTS} value={value} onChange={pick} disabled={() => busy} />
        ))}
        {noteAt('news')}
      </div>
    </Sheet>
    <Sheet title="Instant">{gate('instant', kindRows(INSTANT, 'instant'))}{noteAt('instant')}</Sheet>
    <Sheet title="In the digest">{gate('digest', kindRows(DIGEST, 'digest'))}{noteAt('digest')}</Sheet>
    <Sheet title="Breaking news threshold">
      {gate('impact', (
        <Row label="Breaking news from impact">
          <Segmented label="Breaking news from impact" options={IMPACT} value={minImpact} onChange={pickImpact} disabled={() => busy} />
        </Row>
      ))}
      {noteAt('impact')}
    </Sheet>
    </>
  );
};

export default Notifications;
