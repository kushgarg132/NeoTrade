import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import { splitAmounts } from '../../utils/aiText';
import { formatDateTime } from '../../utils/formatters';

/** Text with rupee amounts wearing the privacy mask. */
export const AiText = ({ text, className = '' }) => (
  <p className={`private text-[15px] text-[var(--text)] ${className}`}>
    {splitAmounts(text).map((p, i) => (p.amount ? <span key={i} className="figure-md">{p.text}</span> : p.text))}
  </p>
);

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
