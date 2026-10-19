import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import { formatDateTime } from '../../utils/formatters';
import { amountParts } from '../../utils/summaries';

/** Text with its rupee amounts under the hide-amounts toggle. */
export const AmountText = ({ text }) => (
  <>
    {amountParts(text).map((p, i) => (p.amount
      ? <span key={i} className="private"><span className="figure-md">{p.text}</span></span>
      : <React.Fragment key={i}>{p.text}</React.Fragment>))}
  </>
);

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
            <div className="mt-2 space-y-2 text-[15px] text-[var(--text)]">
              {s.text.split('\n').filter(Boolean).map((line, i) => <p key={i}><AmountText text={line} /></p>)}
            </div>
          </>
        )}
    </Card>
  );
};

export default AiSummary;
