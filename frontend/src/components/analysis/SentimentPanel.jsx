import React from 'react';
import { Sheet } from '../doc/Doc';
import { cn } from '../../utils/cn';
import Markdown from '../common/Markdown';

/**
 * News sentiment as a calibrated reading rather than a dial: the scale is
 * printed, the needle sits on it, and the number is stated. A gauge that only
 * shows a coloured arc makes the reader guess at the value.
 */
const read = (score) => {
  if (score >= 0.15) return { label: 'Bullish', tone: 'text-up' };
  if (score <= -0.15) return { label: 'Bearish', tone: 'text-down' };
  return { label: 'Neutral', tone: 'text-[var(--ink-soft)]' };
};

const SentimentPanel = ({ score, summary, sentiment, thesis }) => {
  const value = Number(score) || 0;
  const reading = read(value);
  const position = ((value + 1) / 2) * 100;

  return (
    <Sheet title="News sentiment" className="h-full">
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn('font-[family-name:var(--font-narrow)] font-bold uppercase tracking-[0.11em] text-lg', reading.tone)}>
          {reading.label}
        </span>
        <span className="figure-md text-base">{value.toFixed(2)}</span>
      </div>

      <div className="mt-3">
        <div
          className="relative h-6 border border-[var(--rule-strong)] bg-[var(--paper-sunk)]"
          role="img"
          aria-label={`Sentiment ${value.toFixed(2)} on a scale from −1 bearish to +1 bullish`}
        >
          <div className="absolute inset-y-0 left-1/2 w-px bg-[var(--rule-strong)]" aria-hidden="true" />
          <div
            className="absolute inset-y-0 w-0.5 bg-[var(--stamp)]"
            style={{ left: `calc(${position}% - 1px)` }}
            aria-hidden="true"
          />
        </div>
        <div className="flex justify-between doc-meta mt-1">
          <span>−1 bearish</span>
          <span>0</span>
          <span>+1 bullish</span>
        </div>
      </div>

      {sentiment && (
        <div className="mt-4 pt-3 border-t border-[var(--rule)] flex justify-between text-sm">
          <span className="text-[var(--ink-soft)]">
            Articles read{' '}
            <span className="figure-md text-[var(--ink)]">{sentiment.article_count || 0}</span>
          </span>
          <span className="text-[var(--ink-soft)]">
            Impact{' '}
            <span className="figure-md text-[var(--ink)]">{sentiment.risk_score || 0}/10</span>
          </span>
        </div>
      )}

      {summary && (
        <Markdown className="mt-3 pt-3 border-t border-[var(--rule)] text-sm text-[var(--ink-soft)] leading-relaxed">
          {summary}
        </Markdown>
      )}

      {thesis && (
        <div className="mt-3 pt-3 border-t border-[var(--rule)]">
          <p className="field-label mb-1.5">Thesis</p>
          <Markdown className="text-sm text-[var(--ink-soft)] leading-relaxed">{thesis}</Markdown>
        </div>
      )}
    </Sheet>
  );
};

export default SentimentPanel;
