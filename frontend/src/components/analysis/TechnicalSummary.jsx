import React from 'react';
import Card from '../ui/Card';
import { toneText } from '../ui/tone';
import { techSummary } from '../../utils/stock';

const READ = { bull: ['Bullish', 'gain'], bear: ['Bearish', 'loss'], neutral: ['Neutral', 'neutral'] };

/** What the indicators say, counted: a reading, not a recommendation. */
const TechnicalSummary = ({ t }) => {
  const s = techSummary(t);
  if (!s) return null;
  return (
    <Card title="Technical summary">
      <p className={`text-[17px] font-semibold ${toneText(s.tone)}`}>{s.label}</p>
      <p className="text-[13px] text-[var(--text-muted)]">{s.bull} bullish · {s.bear} bearish · {s.neutral} neutral, daily bars</p>
      <ul className="mt-3">
        {s.rows.map((r) => (
          <li key={r.name} className="flex justify-between min-h-9 items-center border-t border-[var(--border)] text-[14px]">
            <span className="text-[var(--text-muted)]">{r.name}</span>
            <span className={`font-semibold ${toneText(READ[r.read][1])}`}>{READ[r.read][0]}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-[var(--text-muted)]">A count of indicator readings, not advice.</p>
    </Card>
  );
};

export default TechnicalSummary;
