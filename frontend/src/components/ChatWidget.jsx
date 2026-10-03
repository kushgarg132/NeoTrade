import React, { useEffect, useRef, useState } from 'react';
import { MessageSquare, X, Send, Loader2, Maximize2, Minimize2 } from 'lucide-react';
import Markdown from './common/Markdown';
import { stream } from '../lib/ws';
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
    "Ask about a scrip, a position, or what the engine is doing. I read the same data the statement does.",
};

const ChatWidget = () => {
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
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  const submit = (event) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;

    const history = messages
      .filter((message) => message !== OPENING)
      .map(({ role, content }) => ({ role, content }));

    setMessages((list) => [...list, { role: 'user', content: text }]);
    setInput('');
    setBusy(true);
    setThinking('');

    let answer = '';
    const request = stream.request('chat', { message: text, history }, (event_) => {
      if (event_.event === 'thinking') {
        setThinking(event_.data.text);
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
            {messages.map((message, index) => (
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
            ))}

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
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about a scrip or a position"
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
