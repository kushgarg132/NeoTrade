import React, { useState } from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Badge from '../ui/Badge';
import { AiMarkdown } from '../ai/AiSummary';
import { splitThesis } from '../../utils/aiRead';
import { formatDateTime } from '../../utils/formatters';

const label = (s) => (s >= 0.15 ? ['Bullish', 'text-[var(--gain)]'] : s <= -0.15 ? ['Bearish', 'text-[var(--loss)]'] : ['Neutral', 'text-[var(--text-muted)]']);

const stageCopy = (stage) =>
  stage?.step === 'news' ? (stage.count != null ? `Reading ${stage.count} headlines…` : 'Reading headlines…')
    : stage?.step === 'writing' ? 'Writing the note…' : null;

/** The AI read on top of /stock/:symbol: last read at once, refreshed and streamed when stale. */
const AiRead = ({ aiRead, retryAi }) => {
  const [open, setOpen] = useState(false);
  const { read, at, stale, stage, text, streaming, error, loading } = aiRead;
  const live = text ? splitThesis(text) : null;
  const summary = live ? live.summary : read?.analyst_summary;
  const thesis = live ? live.thesis : read?.thesis;
  const score = read?.sentiment?.score ?? read?.sentiment_score;
  const [word, tone] = label(Number(score) || 0);
  const updating = stale && !error && (loading || streaming);
  const copy = stageCopy(stage);

  return (
    <Card title="AI read" className="mb-3" action={updating && read ? <Badge>Updating…</Badge> : null}>
      <div id="ai-read" />
      {!summary && error && <ErrorLine message={`Could not load the AI read: ${error}`} onRetry={retryAi} />}
      {!summary && !error && (
        <>
          <p className="mb-2 text-[13px] text-[var(--text-muted)]" role="status">{copy || 'Loading the AI read…'}</p>
          <Skeleton rows={3} />
        </>
      )}
      {summary && (
        <>
          {read && !live && score != null && (
            <p className="mb-2 flex items-baseline justify-between gap-3">
              <span className={`text-[17px] font-bold ${tone}`}>{word}</span>
              <span className="tabular-nums text-[15px] font-semibold">{Number(score).toFixed(2)}</span>
            </p>
          )}
          {copy && <p className="mb-2 text-[13px] text-[var(--text-muted)]" role="status">{copy}</p>}
          <div className={open ? '' : 'line-clamp-3'}><AiMarkdown text={summary} collapse={false} /></div>
          {open && thesis && (
            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              <p className="text-[13px] text-[var(--text-muted)] mb-1.5">Thesis</p>
              <AiMarkdown text={thesis} collapse={false} />
            </div>
          )}
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
            className="block min-h-11 text-[14px] font-semibold text-[var(--accent)]">
            {open ? 'Show less' : 'Read more'}
          </button>
          {read && (
            <p className="text-[13px] text-[var(--text-muted)]">
              {read.sentiment?.relevant_count != null && `Based on ${read.sentiment.relevant_count} articles · `}
              {at ? `as of ${formatDateTime(at)}` : ''}
            </p>
          )}
          {error && (
            <div className="text-[var(--text-muted)]">
              <ErrorLine message={`Couldn't refresh: ${error}`} onRetry={retryAi} />
            </div>
          )}
        </>
      )}
    </Card>
  );
};

export default AiRead;
