import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, MessageCircle, Sparkles } from 'lucide-react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import { formatDateTime } from '../../utils/formatters';
import api, { endpoints } from '../../utils/api';
import {
  parseBlocks, parseInline, collapseBlocks, contentUnits, COLLAPSED_UNITS, outline, tickerCandidates, followUps,
} from '../../utils/aiMarkdown';

// Shared AI-summary pieces: cached-text cards (AiCard/AiText/AiState) and stored-summary cards (default AiSummary).
// Every AI text gets tappable stock chips, toned figures, key points first, tap-to-expand sections and
// follow-up questions that open the chat (spec docs/superpowers/specs/2026-11-02-interactive-ai-cards-design.md).

const TONE = { gain: 'text-[var(--gain)]', loss: 'text-[var(--loss)]' };
const Symbols = React.createContext(null); // { known: Set, change: { SYMBOL: pct } }

/** Day change for the ticker-like words in `text`; only names the quote endpoint knows come back. */
const useTickers = (text) => {
  const wanted = React.useMemo(() => tickerCandidates(text), [text]);
  const [quotes, setQuotes] = React.useState({});
  React.useEffect(() => {
    if (!wanted.length) return undefined;
    let live = true;
    api.get(endpoints.marketQuotes(wanted))
      .then((r) => live && setQuotes(Object.fromEntries((r.data || []).map((q) => [q.symbol, q.change_pct]))))
      .catch(() => {});  // no chips is fine: the text still reads
    return () => { live = false; };
  }, [wanted]);
  return React.useMemo(() => ({ known: new Set(Object.keys(quotes)), change: quotes }), [quotes]);
};

const StockChip = ({ symbol, change }) => (
  <Link to={`/stock/${symbol}`} className="tap inline-flex items-baseline gap-1 rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-[13px] font-semibold text-[var(--text)] no-underline hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]">
    {symbol}
    {typeof change === 'number' && (
      <span className={`figure-md text-[12px] ${change < 0 ? TONE.loss : TONE.gain}`}>{change > 0 ? '+' : ''}{change.toFixed(1)}%</span>
    )}
  </Link>
);

/** One line of AI text: **bold**, *italic*, toned figures, stock chips, rupee amounts under the hide-amounts toggle. */
export const AiInline = ({ text }) => {
  const symbols = React.useContext(Symbols);
  return (
    <>
      {parseInline(text, symbols?.known).map((s, i) => {
        let el = s.text;
        if (s.symbol) el = <StockChip symbol={s.symbol} change={symbols.change[s.symbol]} />;
        else if (s.amount) el = <span className="private"><span className={`figure-md ${TONE[s.tone] || ''}`}>{el}</span></span>;
        else if (s.pct) el = <span className={`figure-md font-semibold ${TONE[s.tone] || ''}`}>{el}</span>;
        if (s.bold) el = <strong className="font-semibold">{el}</strong>;
        if (s.italic) el = <em>{el}</em>;
        return <React.Fragment key={i}>{el}</React.Fragment>;
      })}
    </>
  );
};

const HEADING = ['text-[17px] font-bold', 'text-[16px] font-bold', 'text-[15px] font-semibold'];


const Block = ({ b, i }) => {
  const rise = { className: 'ai-rise', style: { animationDelay: `${Math.min(i, 8) * 40}ms` } };
  if (b.type === 'heading') {
    return <p {...rise} className={`${rise.className} ${HEADING[Math.min(b.level, 3) - 1]} pt-1 text-[var(--text)]`}><AiInline text={b.text} /></p>;
  }
  if (b.type === 'hr') return <hr className="border-[var(--border)]" />;
  if (b.type === 'ul' || b.type === 'ol') {
    const List = b.type;
    return (
      <List {...rise} className={`${rise.className} pl-5 space-y-1 ${b.type === 'ul' ? 'list-disc' : 'list-decimal'} marker:text-[var(--text-muted)]`}>
        {b.items.map((it, j) => <li key={j}><AiInline text={it} /></li>)}
      </List>
    );
  }
  return <p {...rise}><AiInline text={b.text} /></p>;
};

/** "Ask about this": tapping a question opens the chat with this text as what the assistant said. */
const FollowUps = ({ text, title, symbols }) => {
  const questions = followUps(text, [...symbols.known]);
  const ask = (question) => window.dispatchEvent(new CustomEvent('margin-note:ask', { detail: { question, title, text } }));
  return (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      <MessageCircle className="w-4 h-4 text-[var(--text-muted)]" aria-hidden="true" />
      {questions.map((q) => (
        <button key={q} type="button" onClick={() => ask(q)}
          className="tap min-h-11 rounded-full border border-[var(--border)] px-3 text-[13px] font-medium text-[var(--accent)] hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]">
          {q}
        </button>
      ))}
    </div>
  );
};

/** AI-written markdown as React elements, never as HTML: key points first, each heading a tap-to-expand
    section, follow-up questions under it. Long heading-less texts keep a "Read more" toggle. */
export const AiMarkdown = ({ text, className = '', collapse = true, title = 'An AI summary', ask = true }) => {
  const [open, setOpen] = React.useState(false);
  const symbols = useTickers(text);
  const blocks = parseBlocks(text);
  const { lead, leadTitle, intro, sections } = outline(blocks);
  const long = collapse && !sections.length && contentUnits(intro) > COLLAPSED_UNITS;
  const shown = long && !open ? collapseBlocks(intro) : intro;
  const rich = contentUnits(blocks) >= 2;
  return (
    <Symbols.Provider value={symbols}>
      <div className={`space-y-2.5 text-[15px] leading-6 text-[var(--text)] ${className}`}>
        {lead && (rich ? (
          <div className="ai-rise rounded-[14px] bg-[var(--accent-soft)] px-3.5 py-3">
            <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[var(--accent)]">{leadTitle || 'Key points'}</p>
            <Block b={lead} i={0} />
          </div>
        ) : <Block b={lead} i={0} />)}
        {shown.map((b, i) => <Block key={i} b={b} i={i + 1} />)}
        {long && (
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
            className="text-[14px] font-semibold text-[var(--accent)] min-h-11 focus-visible:outline-2 focus-visible:outline-[var(--accent)]">
            {open ? 'Show less' : 'Read more'}
          </button>
        )}
        {sections.map((sec, i) => (
          <details key={sec.title + i} className="ai-section ai-rise group border-t border-[var(--border)]" style={{ animationDelay: `${Math.min(i + shown.length + 1, 8) * 40}ms` }}>
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-[15px] font-semibold text-[var(--text)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]">
              <span><AiInline text={sec.title} /></span>
              <ChevronDown className="w-4 h-4 shrink-0 text-[var(--text-muted)] transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="space-y-2.5 pb-2">{sec.blocks.map((b, j) => <Block key={j} b={b} i={0} />)}</div>
          </details>
        ))}
        {ask && rich && <FollowUps text={text} title={title} symbols={symbols} />}
      </div>
    </Symbols.Provider>
  );
};

/** Kept name for the cached-text cards. */
export const AiText = ({ text, className = '', collapse = true, title }) => <AiMarkdown text={text} className={className} collapse={collapse} title={title} />;

/** A Card marked as AI-written, with when it was written. */
export const AiCard = ({ title, asOf, children, className = '' }) => (
  <Card
    title={title}
    className={`ai-card ${className}`}
    action={<span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[12px] text-[var(--text-muted)]"><Sparkles className="w-3.5 h-3.5 shrink-0 text-[var(--accent)]" aria-hidden="true" />{`AI summary${asOf ? ` · ${asOf.includes('T') ? formatDateTime(asOf) : asOf}` : ''}`}</span>}
  >
    {children}
  </Card>
);

/** loading / error states shared by the stored-text cards; returns null when ok. */
export const AiState = ({ status, retry, message }) => {
  if (status === 'loading') return <Skeleton rows={3} />;
  if (status === 'error') return <ErrorLine message={message} onRetry={retry} />;
  return null;
};

/** Kept name for one-line places (Home brief lines, holding notes). */
export const AmountText = AiInline;

/** "AI summary" with when it was written: the label every generated summary carries. */
export const AiLabel = ({ at }) => (
  <p className="flex items-center gap-1 whitespace-nowrap text-[12px] font-medium text-[var(--text-muted)]">
    <Sparkles className="w-3.5 h-3.5 shrink-0 text-[var(--accent)]" aria-hidden="true" />
    {`AI summary${at ? ` · ${formatDateTime(at)}` : ''}`}
  </p>
);

/**
 * A card for one stored AI summary. `state` is a useLoad result whose data is the endpoint's
 * `{ summary }`; the page never asks a model, it only reads what a job wrote.
 */
const AiSummary = ({ title, state, emptyBody, className = '' }) => {
  const { data, loading, error, reload } = state;
  const s = data?.summary;
  return (
    <Card title={title} className={`ai-card ${className}`}>
      {loading && !data ? <Skeleton rows={3} />
        : error ? <ErrorLine message="Could not load this summary." onRetry={reload} />
        : !s ? <Empty title="No summary yet" body={emptyBody} />
        : (
          <>
            <AiLabel at={s.at} />
            <AiMarkdown text={s.text} className="mt-2" title={title} />
          </>
        )}
    </Card>
  );
};

export default AiSummary;
