import React, { useState } from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import { AiMarkdown } from '../ai/AiSummary';
import { splitThesis } from '../../utils/aiRead';
import { formatDateTime } from '../../utils/formatters';

const label = (s) => (s >= 0.15 ? ['Bullish', 'text-[var(--gain)]'] : s <= -0.15 ? ['Bearish', 'text-[var(--loss)]'] : ['Neutral', 'text-[var(--text-muted)]']);

const stageCopy = (stage) =>
  stage?.step === 'news' ? (stage.count != null ? `Reading ${stage.count} headlines…` : 'Reading headlines…')
    : stage?.step === 'writing' ? 'Writing the note…' : null;

/** The AI read on top of /stock/:symbol: the last read at once; a new one (streamed) only when asked, from
 *  Generate when there is none or Refresh when it is stale. */
const AiRead = ({ aiRead, retryAi }) => {
  const [open, setOpen] = useState(false);
  const { read, at, stale, stage, text, streaming, error, loading } = aiRead;
  const live = text ? splitThesis(text) : null;
  // A fresh run's report says analyst_summary/sentiment; the stored read (analyst.py::latest) summary/sentiment_analysis.
  const summary = live ? live.summary : read?.analyst_summary ?? read?.summary;
  const relevant = (read?.sentiment ?? read?.sentiment_analysis)?.relevant_count;
  const thesis = live ? live.thesis : read?.thesis;
  const score = read?.sentiment?.score ?? read?.sentiment_score;
  const [word, tone] = label(Number(score) || 0);
  const updating = stale && !error && (loading || streaming);
  const copy = stageCopy(stage);
  const busy = loading || streaming;
  const refresh = read && stale && !busy && !error
    ? <Button variant="secondary" onClick={retryAi} className="-my-2.5">Refresh</Button> : null;
  const sentiment = read && !live && score != null && (
    <span className="inline-flex items-baseline gap-1.5">
      <span className={`text-[15px] font-bold ${tone}`}>{word}</span>
      <span className="tabular-nums text-[13px] font-semibold text-[var(--text-muted)]">{Number(score).toFixed(2)}</span>
    </span>
  );

  // No read yet: one row, title and the button that makes one.
  if (!summary && !error && !busy) {
    return (
      <section id="ai-read" className="mb-3 flex items-center justify-between gap-3 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-[var(--text)]">AI read</h2>
          <p className="text-[13px] text-[var(--text-muted)]">No read on this stock yet.</p>
        </div>
        <Button variant="secondary" onClick={retryAi}>Generate</Button>
      </section>
    );
  }

  return (
    <Card title="AI read" className="mb-3" action={(
      <span className="inline-flex items-center gap-3">
        {summary && sentiment}
        {updating && read ? <Badge>Updating…</Badge> : refresh}
      </span>
    )}>
      <div id="ai-read" />
      {!summary && error && <ErrorLine message={`Could not load the AI read: ${error}`} onRetry={retryAi} />}
      {!summary && !error && busy && (
        <>
          <p className="mb-2 text-[13px] text-[var(--text-muted)]" role="status">{copy || 'Loading the AI read…'}</p>
          <Skeleton rows={2} />
        </>
      )}
      {summary && (
        <>
          {copy && <p className="mb-2 text-[13px] text-[var(--text-muted)]" role="status">{copy}</p>}
          <div className={open ? '' : 'line-clamp-3'}><AiMarkdown text={summary} collapse={false} /></div>
          {open && thesis && (
            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              <p className="text-[13px] text-[var(--text-muted)] mb-1.5">Thesis</p>
              <AiMarkdown text={thesis} collapse={false} />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-x-3 -mb-2">
            <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              className="min-h-11 text-[14px] font-semibold text-[var(--accent)]">
              {open ? 'Show less' : 'Read more'}
            </button>
            {read && (
              <p className="text-[12px] text-[var(--text-muted)]">
                {relevant != null && `${relevant} articles · `}
                {at ? formatDateTime(at) : ''}
              </p>
            )}
          </div>
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
