import React, { useEffect, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { Sheet, Empty } from '../doc/Doc';
import { Button } from '../common/Button';
import Markdown from '../common/Markdown';
import api, { endpoints } from '../../utils/api';
import { formatNoteDate, formatTimeAgo } from '../../utils/formatters';

/**
 * Why an index moved in its latest session, written by the analysis model
 * from the session's figures, the other indices, the day's movers and recent
 * headlines -- all gathered on the server first, and listed here so the
 * reader can check what it was written from. Asked for as soon as the index
 * opens: the explanation is the reason the reader tapped.
 */
const IndexAnalysis = ({ ticker }) => {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  // Mounted once per index (the statement keys it on the ticker), so state
  // starts empty for each one; a retry clears the error before refetching.
  useEffect(() => {
    let cancelled = false;
    api
      .get(endpoints.marketIndexAnalysis(ticker))
      .then((res) => !cancelled && setReport(res.data))
      .catch((err) => !cancelled && setError(err?.response?.data?.detail || 'The analysis did not load'));
    return () => {
      cancelled = true;
    };
  }, [ticker, attempt]);

  const title = (
    <span className="inline-flex items-center gap-1.5">
      <Sparkles className="w-3.5 h-3.5 text-[var(--stamp)]" aria-hidden="true" />
      Why it moved
    </span>
  );

  if (error) {
    return (
      <Sheet title={title}>
        <Empty
          title="Could not write the analysis"
          detail={error}
          action={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setError(null);
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </Button>
          }
        />
      </Sheet>
    );
  }

  if (!report) {
    return (
      <Sheet title={title} meta="AI">
        <div className="flex items-center gap-3 py-6 justify-center text-[var(--ink-soft)]" role="status">
          <Loader2 className="w-4 h-4 animate-spin text-[var(--stamp)]" />
          <span className="text-sm">Reading the session and today's headlines…</span>
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet title={title} meta={`AI · ${formatNoteDate(new Date(report.session.date))}`}>
      <Markdown className="text-sm leading-relaxed text-[var(--ink-soft)]">{report.analysis}</Markdown>

      {report.headlines.length > 0 && (
        <div className="mt-5 pt-3 border-t border-[var(--rule)]">
          <p className="field-label mb-1">Headlines it read</p>
          <ul>
            {report.headlines.map((headline) => (
              <li key={headline.url || headline.title} className="border-b border-[var(--rule)] last:border-b-0">
                <a
                  href={headline.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-baseline justify-between gap-4 py-2 hover:bg-[var(--paper-sunk)] -mx-2 px-2 transition-colors"
                >
                  <span className="text-sm min-w-0 group-hover:underline decoration-[var(--stamp)] underline-offset-2">
                    {headline.title}
                  </span>
                  <span className="doc-meta shrink-0 text-right">
                    {headline.source}
                    <span className="block">{formatTimeAgo(headline.published_at)}</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-4 doc-meta normal-case">
        Written by AI {formatTimeAgo(report.generated_at)} from the session figures and these
        headlines. It explains what happened; it is not advice.
      </p>
    </Sheet>
  );
};

export default IndexAnalysis;
