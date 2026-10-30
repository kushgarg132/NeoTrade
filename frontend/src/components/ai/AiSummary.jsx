import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import { formatDateTime } from '../../utils/formatters';
import { parseBlocks, parseInline, collapseBlocks, contentUnits, COLLAPSED_UNITS } from '../../utils/aiMarkdown';

// Shared AI-summary pieces: cached-text cards (AiCard/AiText/AiState) and stored-summary cards (default AiSummary).

/** One line of AI text: **bold**, *italic*, rupee amounts under the hide-amounts toggle. */
export const AiInline = ({ text }) => (
  <>
    {parseInline(text).map((s, i) => {
      let el = s.text;
      if (s.amount) el = <span className="private"><span className="figure-md">{el}</span></span>;
      if (s.bold) el = <strong className="font-semibold">{el}</strong>;
      if (s.italic) el = <em>{el}</em>;
      return <React.Fragment key={i}>{el}</React.Fragment>;
    })}
  </>
);

const HEADING = ['text-[17px] font-bold', 'text-[16px] font-bold', 'text-[15px] font-semibold'];


/** AI-written markdown (headings, paragraphs, lists, rules) as React elements; never as HTML.
    Long texts show their first blocks with a "Read more" toggle so a card never fills the page. */
export const AiMarkdown = ({ text, className = '', collapse = true }) => {
  const [open, setOpen] = React.useState(false);
  const blocks = parseBlocks(text).filter((b, i, all) => !(b.type === 'hr' && (i === 0 || i === all.length - 1)));
  const long = collapse && contentUnits(blocks) > COLLAPSED_UNITS + 1;
  const shown = long && !open ? collapseBlocks(blocks) : blocks;
  return (
  <div className={`space-y-2.5 text-[15px] leading-6 text-[var(--text)] ${className}`}>
    {shown.map((b, i) => {
      if (b.type === 'heading') {
        return <p key={i} className={`${HEADING[Math.min(b.level, 3) - 1]} pt-1 text-[var(--text)]`}><AiInline text={b.text} /></p>;
      }
      if (b.type === 'hr') return <hr key={i} className="border-[var(--border)]" />;
      if (b.type === 'ul' || b.type === 'ol') {
        const List = b.type === 'ul' ? 'ul' : 'ol';
        return (
          <List key={i} className={`pl-5 space-y-1 ${b.type === 'ul' ? 'list-disc' : 'list-decimal'} marker:text-[var(--text-muted)]`}>
            {b.items.map((it, j) => <li key={j}><AiInline text={it} /></li>)}
          </List>
        );
      }
      return <p key={i}><AiInline text={b.text} /></p>;
    })}
    {long && (
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="text-[14px] font-semibold text-[var(--accent)] min-h-11 focus-visible:outline-2 focus-visible:outline-[var(--accent)]">
        {open ? 'Show less' : 'Read more'}
      </button>
    )}
  </div>
  );
};

/** Kept name for the cached-text cards. */
export const AiText = ({ text, className = '', collapse = true }) => <AiMarkdown text={text} className={className} collapse={collapse} />;

/** A Card marked as AI-written, with when it was written. */
export const AiCard = ({ title, asOf, children, className = '' }) => (
  <Card
    title={title}
    className={className}
    action={<span className="text-[12px] text-[var(--text-muted)]">AI summary{asOf ? ` · ${asOf.includes('T') ? formatDateTime(asOf) : asOf}` : ''}</span>}
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
  <p className="text-[12px] font-medium text-[var(--text-muted)]">
    AI summary{at ? ` · ${formatDateTime(at)}` : ''}
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
    <Card title={title} className={className}>
      {loading && !data ? <Skeleton rows={3} />
        : error ? <ErrorLine message="Could not load this summary." onRetry={reload} />
        : !s ? <Empty title="No summary yet" body={emptyBody} />
        : (
          <>
            <AiLabel at={s.at} />
            <AiMarkdown text={s.text} className="mt-2" />
          </>
        )}
    </Card>
  );
};

export default AiSummary;
