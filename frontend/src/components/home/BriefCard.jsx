import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import Card from '../ui/Card';
import { digestLines } from '../../utils/todayLayout';

/** The pre-market or post-close digest: its first lines, "Read all" for the rest. */
const BriefCard = ({ title, text }) => {
  const [all, setAll] = useState(false);
  const lines = digestLines(text).slice(1); // the first line is the digest's own title
  if (!lines.length) return null;
  const shown = all ? lines : lines.slice(0, 3);
  return (
    <Card title={title}>
      <ul className="space-y-1.5 text-[15px] text-[var(--text)]">
        {shown.map((line, i) => <li key={i}>{line}</li>)}
      </ul>
      {lines.length > 3 && (
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
