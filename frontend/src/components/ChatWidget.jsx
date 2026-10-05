import React, { useEffect, useRef, useState } from 'react';
import { useLocation, matchPath } from 'react-router-dom';
import { MessageSquare, X, Send, Loader2, Maximize2, Minimize2, Check } from 'lucide-react';
import Markdown from './common/Markdown';
import { stream } from '../lib/ws';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';

/**
 * The margin note: an assistant docked to the corner of the sheet.
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

/** Questions worth one tap, by the page the user is on. */
const SUGGESTED = [
  ['/mine/holdings', ['What should I trim?', 'Explain my biggest risk', 'What does the plan say to add?']],
  ['/mine', ['How did I do this month?', "What's my costliest habit?"]],
  ['/ai', ['Is the engine running?', 'Which proposal is strongest?', 'How far is any strategy from going live?']],
  ['/settings', ['What are my limits?', 'Did any guardrail trip today?']],
  ['/profile', ['What do you remember about me?', 'Does my portfolio fit my risk appetite?']],
  ['/', ['How am I doing today?', 'Anything waiting for me?', 'Why did NIFTY move today?']],
];
// '/' is last, so it catches every page without its own list.
const suggestionsFor = (path) =>
  SUGGESTED.find(([prefix]) => prefix === '/' || path === prefix || path.startsWith(`${prefix}/`))[1];

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
        const res = await api.post(endpoints.chat.confirm(action.card.id), {
          second_tap: action.state === 'NEEDS_SECOND_TAP',
        });
        onUpdate({ state: res.data.status, note: res.data.result });
      }
    } catch (err) {
      // No response at all: the confirm may have run. Never call that a failure.
      if (kind !== 'cancel' && !err?.response) onUpdate({ state: 'UNKNOWN', note: 'No answer from the server. The order may have gone through: check Trades before trying again.' });
      else onUpdate({ state: 'FAILED', note: err?.response?.data?.detail || 'That did not go through.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn('border px-3 py-2.5 text-sm', live ? 'border-[var(--loss)]' : 'border-[var(--rule-strong)]')}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="field-label text-[var(--ink)]">Proposed change</span>
        <span className={cn('field-label', live ? 'text-[var(--loss)]' : 'text-[var(--ink-soft)]')}>
          {live ? 'Live · real money' : action.card.venue === 'paper' ? 'Paper' : ''}
        </span>
      </div>
      <p className="figure-md">{action.card.summary}</p>
      {action.state === 'NEEDS_SECOND_TAP' && (
        <p className="mt-1.5 text-[var(--loss)]" role="alert">Real money. Tap Confirm again to send it.</p>
      )}
      {action.note && action.state !== 'NEEDS_SECOND_TAP' && (
        <p className={cn('mt-1.5', action.state === 'FAILED' ? 'text-[var(--loss)]' : 'text-[var(--ink-soft)]')}>
          {action.note}
        </p>
      )}
      {!final && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => run('cancel')}
            disabled={busy}
            className="min-h-9 border border-[var(--rule-strong)] field-label text-[var(--ink)] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => run('confirm')}
            disabled={busy}
            className={cn(
              'min-h-9 inline-flex items-center justify-center gap-1.5 field-label text-white disabled:opacity-50',
              live ? 'bg-[var(--loss)]' : 'bg-[var(--gain)]'
            )}
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            {action.state === 'NEEDS_SECOND_TAP' ? 'Send real order' : 'Confirm'}
          </button>
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
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState([OPENING]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState('');
  // What the assistant suggests asking next, shown under its latest reply.
  const [followups, setFollowups] = useState([]);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking, followups]);

  const updateAction = (id, patch) =>
    setMessages((list) => list.map((m) => (m.role === 'action' && m.card.id === id ? { ...m, ...patch } : m)));

  const submit = (event) => {
    event.preventDefault();
    send(input.trim());
  };

  const send = (text) => {
    if (!text || busy) return;

    const history = messages
      .filter((message) => message !== OPENING && message.role !== 'action')
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
    // A stock page carries its symbol in the URL (/research/stock/:symbol).
    const symbol = matchPath('/research/stock/:symbol', location.pathname)?.params.symbol || location.state?.symbol;
    const context = { page: location.pathname, symbol };
    const request = stream.request('chat', { message: text, history, context }, (event_) => {
      if (event_.event === 'suggestions') {
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

    if (!request.ok) {
      setBusy(false);
      setThinking('');
      setMessages((list) => [
        ...list,
        { role: 'assistant', content: 'The live connection is down, so I cannot answer right now.' },
      ]);
    }
  };

  return (
    <div className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-4 lg:bottom-6 lg:right-6 z-50 flex flex-col items-end pointer-events-none">
      {open && (
        <div
          className={cn(
            'mb-3 sheet flex flex-col overflow-hidden pointer-events-auto',
            expanded ? 'w-[min(34rem,calc(100vw-2rem))] h-[70vh]' : 'w-[min(22rem,calc(100vw-2rem))] h-[26rem]'
          )}
        >
          <header className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--rule-strong)] bg-[var(--paper-sunk)]">
            <span className="field-label text-[var(--ink)]">Margin note</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="p-1 text-[var(--ink-soft)] hover:text-[var(--ink)]"
                aria-label={expanded ? 'Shrink' : 'Expand'}
              >
                {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="p-1 text-[var(--ink-soft)] hover:text-[var(--ink)]"
                aria-label="Close"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.map((message, index) =>
              message.role === 'action' ? (
                <ActionCard
                  key={message.card.id}
                  action={message}
                  onUpdate={(patch) => updateAction(message.card.id, patch)}
                />
              ) : (
              <div key={index} className={cn(message.role === 'user' && 'text-right')}>
                <p className="field-label mb-1">{message.role === 'user' ? 'You' : 'Assistant'}</p>
                <div
                  className={cn(
                    'inline-block text-left text-sm leading-relaxed px-3 py-2 border max-w-[92%]',
                    message.role === 'user'
                      ? 'border-[var(--rule-strong)] bg-[var(--paper-sunk)]'
                      : 'border-[var(--rule)]'
                  )}
                >
                  <Markdown>{message.content}</Markdown>
                </div>
              </div>
              )
            )}

            {!busy && (messages.length === 1 || followups.length > 0) && (
              <div className="flex flex-wrap gap-1.5">
                {(messages.length === 1 ? suggestionsFor(location.pathname) : followups).map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => send(question)}
                    className="min-h-11 lg:min-h-0 px-2.5 py-1.5 border border-[var(--rule-strong)] text-xs text-[var(--ink)] hover:bg-[var(--stamp-soft)] active:bg-[var(--stamp-soft)] text-left touch-manipulation"
                  >
                    {question}
                  </button>
                ))}
              </div>
            )}

            {busy && (
              <div className="flex items-center gap-2 text-[var(--ink-soft)]">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--stamp)] shrink-0" />
                <span className="doc-meta normal-case truncate">{thinking || 'Thinking…'}</span>
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={submit} className="flex items-center gap-2 px-3 py-2 border-t border-[var(--rule-strong)]">
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about your account or a stock"
              disabled={busy}
              className="flex-1 bg-transparent border-0 py-1.5 text-sm focus:outline-none disabled:opacity-50"
              aria-label="Message"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="p-1.5 text-[var(--stamp)] disabled:opacity-30"
              aria-label="Send"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="pointer-events-auto hidden lg:flex w-11 h-11 border border-[var(--rule-strong)] bg-[var(--paper)] text-[var(--ink)] items-center justify-center shadow-[var(--sheet-shadow)] hover:bg-[var(--stamp-soft)] transition-colors"
        aria-label={open ? 'Close the margin note' : 'Open the margin note'}
      >
        {open ? <X className="w-5 h-5" /> : <MessageSquare className="w-5 h-5" />}
      </button>
    </div>
  );
};

export default ChatWidget;
