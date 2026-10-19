import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import Card from '../ui/Card';
import { AiLabel, AmountText } from '../ai/AiSummary';
import { digestLines } from '../../utils/todayLayout';
import { summaryLines } from '../../utils/summaries';

/**
 * Your day. The AI's three lines when a job has written them (`summary`, from /summaries/day), else the
 * pre-market or post-close digest's first lines with "Read all" for the rest.
 */
const BriefCard = ({ title, text, summary }) => {
  const [all, setAll] = useState(false);
  const ai = summaryLines(summary?.text);
  const lines = ai.length ? ai : digestLines(text).slice(1); // the digest's first line is its own title
  if (!lines.length) return null;
  const shown = all || ai.length ? lines : lines.slice(0, 3);
  return (
    <Card title={title}>
      {ai.length > 0 && <div className="mb-2"><AiLabel at={summary.at} /></div>}
      <ul className="space-y-1.5 text-[15px] text-[var(--text)]">
        {shown.map((line, i) => <li key={i}>{ai.length ? <AmountText text={line} /> : line}</li>)}
      </ul>
      {!ai.length && lines.length > 3 && (
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
                className="mt-1 inline-flex items-center gap-1 min-h-11 text-[14px] font-semibold text-[var(--accent)] active:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          {all ? 'Show less' : 'Read all'}
          <ChevronDown className={`w-4 h-4 transition-transform ${all ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
      )}
    </Card>
  );
};

export default BriefCard;
