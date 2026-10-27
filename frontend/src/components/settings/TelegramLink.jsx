import React, { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Button } from './Panel';
import api, { endpoints } from '../../utils/api';
import { Row } from './Fields';

/** Telegram bot + chat link: own-bot add/remove, link, verify, unlink. */
const TelegramLink = () => {
  const [telegram, setTelegram] = useState(null);
  const [linkUrl, setLinkUrl] = useState(null);
  const [botToken, setBotToken] = useState('');
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadTelegram = () =>
    api
      .get(endpoints.guardrails.status)
      .then((res) => setTelegram(res.data.telegram))
      .catch(() => setTelegram(null));

  useEffect(() => {
    loadTelegram();
  }, []);

  const act = (request, onDone) => {
    setBusy(true);
    setNote(null);
    request()
      .then(onDone)
      .catch((err) => setNote(err?.response?.data?.detail || 'That did not work'))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <Row
        label="Your Telegram bot"
        hint={
          telegram?.own_bot
            ? `Alerts come from @${telegram.own_bot}. Removing it unlinks your chat.`
            : 'Optional. In Telegram, message @BotFather, send /newbot, and paste the token it gives you. It is stored encrypted and never shown again.'
        }
      >
        {telegram?.own_bot ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => act(() => api.delete(endpoints.guardrails.telegramBot), () => {
              setLinkUrl(null);
              loadTelegram();
            })}
          >
            Remove bot
          </Button>
        ) : (
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              act(() => api.put(endpoints.guardrails.telegramBot, { token: botToken.trim() }), (res) => {
                setBotToken('');
                setLinkUrl(null);
                setTelegram((t) => ({ ...t, configured: true, linked: false, own_bot: res.data.own_bot }));
              });
            }}
          >
            <input
              type="password"
              autoComplete="off"
              value={botToken}
              onChange={(event) => setBotToken(event.target.value)}
              placeholder="123456:ABC…"
              aria-label="Telegram bot token"
              className="min-w-0 w-40 sm:w-56 bg-[var(--surface)] border border-[var(--border)] rounded-[12px] px-3 min-h-11 text-[15px] focus:outline-none focus:border-[var(--accent)]"
            />
            <Button type="submit" variant="primary" size="sm" disabled={busy || !botToken.trim()}>
              Save
            </Button>
          </form>
        )}
      </Row>

      <Row
        label="Telegram alerts"
        hint={
          telegram?.configured === false
            ? 'Add your own bot above to get alerts on your phone. They still appear in the app.'
            : 'Alerts arrive on your phone even when the app is closed.'
        }
      >
        {telegram?.configured &&
          (telegram.linked ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() =>
                act(() => api.delete(endpoints.guardrails.telegram), () =>
                  setTelegram((t) => ({ ...t, linked: false }))
                )
              }
            >
              Unlink
            </Button>
          ) : linkUrl ? (
            <div className="flex gap-2">
              <a href={linkUrl} target="_blank" rel="noreferrer">
                <Button variant="secondary" size="sm">
                  <ExternalLink className="w-3.5 h-3.5" />
                  Open Telegram
                </Button>
              </a>
              <Button
                variant="primary"
                size="sm"
                disabled={busy}
                onClick={() =>
                  act(() => api.post(endpoints.guardrails.verify), () => {
                    setLinkUrl(null);
                    setTelegram((t) => ({ ...t, linked: true }));
                  })
                }
              >
                I tapped Start
              </Button>
            </div>
          ) : (
            <Button
              variant="primary"
              size="sm"
              disabled={busy}
              onClick={() => act(() => api.post(endpoints.guardrails.link), (res) => setLinkUrl(res.data.url))}
            >
              Link Telegram
            </Button>
          ))}
      </Row>
      {note && <p role="alert" className="text-[13px] text-[var(--text-muted)] pt-2">{note}</p>}
    </>
  );
};

export default TelegramLink;
