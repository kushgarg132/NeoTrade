import React, { useEffect, useRef, useState } from 'react';
import { useLocation, matchPath } from 'react-router-dom';
import { ArrowUp, Check, Loader2, RotateCcw, Sparkles, X } from 'lucide-react';
import Markdown from './common/Markdown';
import ChatChart from './ChatChart';
import { stream } from '../lib/ws';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import Countdown from './common/Countdown';
import Button from './ui/Button';
import Badge from './ui/Badge';
import { tokenRefusal, deadlineFrom, EXPIRED_NOTE } from '../utils/liveConfirm';

/**
 * The assistant ("Ask NeoTrade"): a full-height bottom panel on a phone (opened from the masthead), a panel docked to the right
 * edge on a desktop (opened from the corner button).
 *
 * Replies stream over the app's socket rather than the old hand-parsed SSE
 * reader, which existed only because EventSource cannot carry an
 * Authorization header.
 */
const OPENING = {
  role: 'assistant',
  content:
    "Ask about anything in your account (portfolio and its history, real and paper trades, engine runs, proposals, settings, watchlist) or a stock. I read only your own data, and anything I would change waits for your Confirm.",
};

/**
 * Questions worth one tap, by the page the user is on. First match wins, so
 * specific routes come before their parents; '/' catches everything else.
 * A function gets the route params (symbol, ticker, name).
 */
const SUGGESTED = [
  ['/stock/:symbol', ({ symbol }) => [`Chart ${symbol} over 6 months`, `Is ${symbol} a buy right now?`, `Compare ${symbol} with its peers`]],
  ['/research/stock/:symbol', ({ symbol }) => [`Summarise the case for ${symbol}`, `Chart ${symbol} against NIFTY`, `What could go wrong with ${symbol}?`]],
  ['/mine/stock/:symbol', ({ symbol }) => [`Chart my ${symbol} position`, `Should I hold or trim ${symbol}?`, `How have I traded ${symbol}?`]],
  ['/ideas/history', () => ['Chart how past ideas did', 'Which setups actually worked?']],
  ['/ideas/:id', () => ['Explain this idea simply', 'Chart the entry, stop and target', 'What would make this fail?']],
  ['/ideas', () => ['Which idea is strongest today?', 'Chart idea win rate by setup', 'Why are these ideas picked?']],
  ['/market/index/:ticker', ({ ticker }) => [`Chart ${ticker} this month`, `Why did ${ticker} move today?`]],
  ['/market/sector/:name', ({ name }) => [`Chart ${name} stocks today`, `What is driving ${name}?`]],
  ['/market', () => ["Chart today's sector moves", 'Why did NIFTY move today?', 'Any big events this week?']],
  ['/money/trade/:id', () => ['What went right or wrong here?', 'Did I follow my plan on this?']],
  ['/money', () => ['Chart my P&L this month', 'Pie chart of my allocation', "What's my costliest habit?"]],
  ['/news/:id', () => ['How does this affect my holdings?', 'Chart the stock since this news']],
  ['/reports/weekly', () => ['Chart my week day by day', 'What should I change next week?']],
  ['/ai/strategy/:name', ({ name }) => [`Chart ${name}'s paper P&L`, `How far is ${name} from going live?`]],
  ['/ai/trade/:id', () => ['Why did the engine take this?', 'How did this trade end?']],
  ['/ai', () => ['Is the engine running?', 'Which proposal is strongest?', 'Chart paper P&L by strategy']],
  ['/settings', () => ['What are my limits?', 'Did any guardrail trip today?']],
  ['/profile', () => ['What do you remember about me?', 'Does my portfolio fit my risk appetite?']],
  ['/', () => ['How am I doing today?', 'Chart my portfolio value', 'Anything waiting for me?']],
];
const suggestionsFor = (path) => {
  for (const [pattern, list] of SUGGESTED) {
    const match = pattern === '/' || matchPath({ path: pattern, end: false }, path);
    if (match) return list(match.params || {});
  }
  return [];
};

/**
 * A change the assistant prepared. Nothing happens until Confirm; a live
 * order takes a second tap, the same as approving one live elsewhere.
 */
const ActionCard = ({ action, onUpdate }) => {
  const [busy, setBusy] = useState(false);
  const live = action.card.venue === 'live';
  const final = ['CONFIRMED', 'CANCELLED', 'FAILED', 'UNKNOWN'].includes(action.state);

  const run = async (kind) => {
    setBusy(true);
    try {
      if (kind === 'cancel') {
        await api.post(endpoints.chat.cancel(action.card.id));
        onUpdate({ state: 'CANCELLED', note: 'Cancelled. Nothing changed.' });
      } else {
        // The second tap presents the token the server returned for the first.
        const res = await api.post(endpoints.chat.confirm(action.card.id), {
          confirm_token: action.state === 'NEEDS_SECOND_TAP' ? action.token : undefined,
        });
        onUpdate({ state: res.data.status, note: res.data.result, token: res.data.confirm_token, until: res.data.confirm_token ? deadlineFrom(res.data.expires_in) : undefined });
      }
    } catch (err) {
      // A refused token leaves the card PROPOSED on the server: back to the first tap.
      const refusal = kind !== 'cancel' && action.token && tokenRefusal(err);
      if (refusal) return onUpdate({ state: 'PROPOSED', note: refusal, token: undefined, until: undefined });
      // No response at all: the confirm may have run. Never call that a failure.
      if (kind !== 'cancel' && !err?.response) onUpdate({ state: 'UNKNOWN', note: 'No answer from the server. The order may have gone through: check Journal before trying again.' });
      else onUpdate({ state: 'FAILED', note: err?.response?.data?.detail || 'That did not go through.' });
    } finally {
      setBusy(false);
    }
  };

  const second = action.state === 'NEEDS_SECOND_TAP';
  return (
    <div className={cn('rounded-[16px] border p-3.5', live ? 'border-[var(--loss)] bg-[var(--loss-soft)]' : 'border-[var(--border)] bg-[var(--surface)]')}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-[var(--text-muted)]">Proposed change</span>
        {live ? <Badge kind="live">Real money</Badge> : action.card.venue === 'paper' ? <Badge kind="paper">Paper</Badge> : null}
      </div>
      <p className="mt-1.5 text-[15px] font-semibold leading-snug text-[var(--text)]">{action.card.summary}</p>
      {second && (
        <p className="mt-2 flex flex-wrap items-center gap-x-2 text-[14px] font-medium text-[var(--loss)]" role="alert">
          Real money. Tap Send to place it.
          {action.until && <span className="text-[var(--text-muted)]"><Countdown until={action.until} onExpire={() => onUpdate({ state: 'PROPOSED', note: EXPIRED_NOTE, token: undefined, until: undefined })} /></span>}
        </p>
      )}
      {action.note && !second && (
        <p className={cn('mt-2 text-[14px]', action.state === 'FAILED' ? 'text-[var(--loss)]' : action.state === 'CONFIRMED' ? 'text-[var(--gain)]' : 'text-[var(--text-muted)]')}>
          {action.state === 'CONFIRMED' && <Check className="mr-1 inline w-4 h-4 align-[-3px]" aria-hidden="true" />}{action.note}
        </p>
      )}
      {!final && (
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" className="px-4" onClick={() => run('cancel')} disabled={busy}>Cancel</Button>
          <Button variant={live ? 'danger' : 'primary'} onClick={() => run('confirm')} disabled={busy}
            className={cn('flex-1', second && 'ring-2 ring-offset-2 ring-offset-[var(--surface)] ring-[var(--warn)]')}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            {second ? 'Send real order' : 'Confirm'}
          </Button>
        </div>
      )}
    </div>
  );
};

const ChatWidget = () => {
  const location = useLocation();
  const [open, setOpen] = useState(false);

  // On a phone the masthead opens it; the floating button is desktop only.
  useEffect(() => {
    const onToggle = () => setOpen((value) => !value);
    window.addEventListener('margin-note:toggle', onToggle);
    return () => window.removeEventListener('margin-note:toggle', onToggle);
  }, []);
  const [messages, setMessages] = useState([OPENING]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState('');
  // What the assistant suggests asking next, shown under its latest reply.
  const [followups, setFollowups] = useState([]);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const requestRef = useRef(null);

  // Leaving (sign-out) cancels the reply still streaming.
  useEffect(() => () => requestRef.current?.cancel(), []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking, followups]);

  // Escape closes; opening focuses the composer on a desktop (on a phone that would raise the keyboard at once).
  useEffect(() => {
    if (!open) return undefined;
    if (window.matchMedia?.('(min-width: 1024px)').matches) inputRef.current?.focus();
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const updateAction = (id, patch) =>
    setMessages((list) => list.map((m) => (m.role === 'action' && m.card.id === id ? { ...m, ...patch } : m)));

  // Starts over: stops a reply still streaming and drops the conversation.
  const clear = () => {
    requestRef.current?.cancel();
    setMessages([OPENING]);
    setFollowups([]);
    setBusy(false);
    setThinking('');
    setInput('');
  };

  const submit = (event) => {
    event.preventDefault();
    send(input.trim());
  };

  const send = (text) => {
    if (!text || busy) return;

    const history = messages
      .filter((message) => message !== OPENING && (message.role === 'user' || message.role === 'assistant'))
      .map(({ role, content }) => ({ role, content }));

    setMessages((list) => [...list, { role: 'user', content: text }]);
    setInput('');
    // On a phone this closes the keyboard; left open, the first tap on a chip
    // only dismisses it and the panel jumps out from under the finger.
    inputRef.current?.blur();
    setBusy(true);
    setThinking('');
    setFollowups([]);

    let answer = '';
    // A stock page carries its symbol in the URL (/stock/:symbol).
    const symbol = matchPath('/stock/:symbol', location.pathname)?.params.symbol || location.state?.symbol;
    const context = { page: location.pathname, symbol };
    const request = stream.request('chat', { message: text, history, context }, (event_) => {
      if (event_.event === 'chart' || event_.event === 'image') {
        answer = '';
        setMessages((list) => {
          const settled = list.map((m) => (m.streaming ? { role: m.role, content: m.content } : m));
          return [...settled, { role: event_.event, data: event_.data }];
        });
      } else if (event_.event === 'suggestions') {
        setFollowups(event_.data);
      } else if (event_.event === 'thinking') {
        setThinking(event_.data.text);
      } else if (event_.event === 'action') {
        answer = '';
        setMessages((list) => {
          const settled = list.map((m) => (m.streaming ? { role: m.role, content: m.content } : m));
          return [...settled, { role: 'action', card: event_.data, state: 'PROPOSED' }];
        });
      } else if (event_.event === 'content') {
        answer += event_.data.text;
        setMessages((list) => {
          const last = list[list.length - 1];
          if (last?.role === 'assistant' && last.streaming) {
            return [...list.slice(0, -1), { role: 'assistant', content: answer, streaming: true }];
          }
          return [...list, { role: 'assistant', content: answer, streaming: true }];
        });
      } else if (event_.event === 'done' || event_.event === 'error') {
        setBusy(false);
        setThinking('');
        setMessages((list) => {
          const last = list[list.length - 1];
          if (event_.event === 'error' && (!last || last.role !== 'assistant' || !last.streaming)) {
            return [...list, { role: 'assistant', content: `Could not answer: ${event_.data.detail}` }];
          }
          if (last?.streaming) {
            return [...list.slice(0, -1), { role: 'assistant', content: last.content }];
          }
          return list;
        });
      }
    });

    requestRef.current = request;
    if (!request.ok) {
      setBusy(false);
      setThinking('');
      setMessages((list) => [
        ...list,
        { role: 'assistant', content: 'The live connection is down, so I cannot answer right now.' },
      ]);
    }
  };

  const fresh = messages.length === 1;
  const chips = !busy && (fresh ? suggestionsFor(location.pathname) : followups);

  return (
    <>
      {open && <div className="fixed inset-0 z-[55] bg-black/50 lg:hidden" onClick={() => setOpen(false)} aria-hidden="true" />}
      {open && (
        <aside
          role="dialog"
          aria-label="Ask NeoTrade"
          className="fade-in fixed z-[56] flex flex-col bg-[var(--surface)] border-[var(--border)]
            inset-x-0 bottom-0 h-[92dvh] rounded-t-[28px] border-t
            lg:inset-x-auto lg:right-0 lg:top-0 lg:h-dvh lg:w-[420px] lg:rounded-none lg:border-t-0 lg:border-l"
        >
          <div className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-[var(--border)] lg:hidden" aria-hidden="true" />
          <header className="flex items-center gap-3 px-5 pt-3 pb-3 lg:pt-5 border-b border-[var(--border)]">
            <span className="inline-flex w-9 h-9 shrink-0 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent)]"><Sparkles className="w-[18px] h-[18px]" aria-hidden="true" /></span>
            <div className="min-w-0 flex-1">
              <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">Ask NeoTrade</h2>
              <p className="text-[12px] text-[var(--text-muted)] truncate">Your data only · nothing changes without Confirm</p>
            </div>
            {messages.length > 1 && (
              <button type="button" onClick={clear} aria-label="Clear the chat" title="Clear the chat"
                className="tap inline-flex w-11 h-11 shrink-0 items-center justify-center rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
                <RotateCcw className="w-5 h-5" />
              </button>
            )}
            <button type="button" onClick={() => setOpen(false)} aria-label="Close the assistant"
              className="tap -mr-2 inline-flex w-11 h-11 shrink-0 items-center justify-center rounded-[12px] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
              <X className="w-5 h-5" />
            </button>
          </header>

          <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4 space-y-4" aria-live="polite">
            {fresh ? (
              <div className="pt-4">
                <h3 className="text-[22px] font-bold leading-tight tracking-[-0.02em] text-[var(--text)]">What do you want to know?</h3>
                <p className="mt-1.5 text-[15px] leading-snug text-[var(--text-muted)]">{OPENING.content}</p>
              </div>
            ) : messages.map((message, index) => {
              if (message === OPENING) return null;
              if (message.role === 'chart') return <ChatChart key={index} spec={message.data} />;
              if (message.role === 'image') {
                return <img key={index} src={message.data.url} alt={message.data.alt} className="w-full rounded-[16px] border border-[var(--border)]" />;
              }
              if (message.role === 'action') {
                return <ActionCard key={message.card.id} action={message} onUpdate={(patch) => updateAction(message.card.id, patch)} />;
              }
              return message.role === 'user' ? (
                <div key={index} className="flex justify-end">
                  <div className="max-w-[85%] rounded-[20px] rounded-br-[6px] bg-[var(--accent)] px-4 py-2.5 text-[15px] leading-snug text-[var(--accent-ink)]">{message.content}</div>
                </div>
              ) : (
                <div key={index} className="text-[15px] leading-relaxed text-[var(--text)] [&_p]:my-1.5 [&_ul]:my-1.5">
                  <Markdown>{message.content}</Markdown>
                </div>
              );
            })}

            {chips?.length > 0 && (
              <div className={cn('flex gap-2', fresh ? 'flex-col items-stretch pt-2' : 'flex-wrap')}>
                {chips.map((question) => (
                  <button key={question} type="button" onClick={() => send(question)}
                    className={cn('tap min-h-11 rounded-[14px] border border-[var(--border)] px-3.5 py-2 text-left text-[14px] text-[var(--text)] hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] touch-manipulation focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]',
                      fresh && 'bg-[var(--surface-2)] text-[15px] font-medium')}>
                    {question}
                  </button>
                ))}
              </div>
            )}

            {busy && (
              <div className="flex items-center gap-2.5 text-[var(--text-muted)]">
                <span className="flex gap-1" aria-hidden="true">
                  {[0, 1, 2].map((i) => <span key={i} className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" style={{ animationDelay: `${i * 150}ms` }} />)}
                </span>
                <span className="text-[13px] truncate">{thinking || 'Thinking…'}</span>
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={submit} className="px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] border-t border-[var(--border)]">
            <div className="flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-2)] pl-4 pr-1.5 focus-within:ring-2 focus-within:ring-[var(--accent)]">
              <input
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask about your account or a stock"
                disabled={busy}
                className="min-h-12 flex-1 min-w-0 bg-transparent border-0 p-0 text-[15px] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-0 disabled:opacity-50"
                aria-label="Message"
              />
              <button type="submit" disabled={busy || !input.trim()} aria-label="Send"
                className="tap inline-flex w-10 h-10 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--accent-ink)] disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-5 h-5" />}
              </button>
            </div>
          </form>
        </aside>
      )}

      {!open && (
        <button type="button" onClick={() => setOpen(true)} aria-label="Open the assistant"
          className="tap fixed bottom-6 right-6 z-50 hidden lg:inline-flex items-center gap-2 min-h-11 rounded-full border border-[var(--border)] bg-[var(--surface)] pl-3.5 pr-4 text-[14px] font-semibold text-[var(--text)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          <Sparkles className="w-4 h-4 text-[var(--accent)]" aria-hidden="true" /> Ask NeoTrade
        </button>
      )}
    </>
  );
};

export default ChatWidget;
