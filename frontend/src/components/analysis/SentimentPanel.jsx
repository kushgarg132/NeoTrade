import React from 'react';
import Card from '../ui/Card';
import Markdown from '../common/Markdown';

/**
 * News sentiment as a calibrated reading rather than a dial: the scale is
 * printed, the needle sits on it, and the number is stated. A gauge that only
 * shows a coloured arc makes the reader guess at the value.
 */
const read = (score) => {
  if (score >= 0.15) return { label: 'Bullish', tone: 'text-[var(--gain)]' };
  if (score <= -0.15) return { label: 'Bearish', tone: 'text-[var(--loss)]' };
  return { label: 'Neutral', tone: 'text-[var(--text-muted)]' };
};

const SentimentPanel = ({ score, summary, sentiment, thesis, more }) => {
  const value = Number(score) || 0;
  const reading = read(value);
  const position = ((value + 1) / 2) * 100;

  return (
    <Card title="News sentiment" more={more}>
      <div className="flex items-baseline justify-between gap-3">
        <span className={`text-[20px] font-bold ${reading.tone}`}>
          {reading.label}
        </span>
        <span className="tabular-nums text-[17px] font-semibold">{value.toFixed(2)}</span>
      </div>

      <div className="mt-3">
        <div
          className="relative h-3 rounded-full bg-[var(--surface-2)]"
          role="img"
          aria-label={`Sentiment ${value.toFixed(2)} on a scale from −1 bearish to +1 bullish`}
        >
          <div className="absolute inset-y-0 left-1/2 w-px bg-[var(--border)]" aria-hidden="true" />
          <div
            className="absolute -inset-y-1 w-1 rounded-full bg-[var(--accent)]"
            style={{ left: `calc(${position}% - 1px)` }}
            aria-hidden="true"
          />
        </div>
        <div className="flex justify-between text-[12px] text-[var(--text-muted)] mt-1">
          <span>−1 bearish</span>
          <span>0</span>
          <span>+1 bullish</span>
        </div>
      </div>

      {sentiment && (
        <div className="mt-4 pt-3 border-t border-[var(--border)] flex justify-between text-[14px]">
          <span className="text-[var(--text-muted)]">
            Articles read{' '}
            <span className="tabular-nums font-medium text-[var(--text)]">{sentiment.article_count || 0}</span>
            {sentiment.relevant_count != null && (
              <>
                {' · relevant '}
                <span className="tabular-nums font-medium text-[var(--text)]">{sentiment.relevant_count}</span>
              </>
            )}
          </span>
          <span className="text-[var(--text-muted)]">
            Impact{' '}
            <span className="tabular-nums font-medium text-[var(--text)]">{sentiment.risk_score || 0}/10</span>
          </span>
        </div>
      )}

      {summary && (
        <Markdown className="mt-3 pt-3 border-t border-[var(--border)] text-[15px] text-[var(--text-muted)] leading-relaxed">
          {summary}
        </Markdown>
      )}

      {thesis && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <p className="text-[13px] text-[var(--text-muted)] mb-1.5">Thesis</p>
          <Markdown className="text-[15px] text-[var(--text-muted)] leading-relaxed">{thesis}</Markdown>
        </div>
      )}
    </Card>
  );
};

export default SentimentPanel;
