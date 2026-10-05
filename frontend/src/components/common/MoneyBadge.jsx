import React from 'react';

const LABELS = { mine: 'Mine', ai: 'AI', paper: 'Paper' };

/** Whose money a figure is: the user's own account, the AI account, or practice.
    `mode` ('paper' | 'live') says which money the AI is trading: AI · paper. */
const MoneyBadge = ({ kind, mode }) => (
  <span className={`badge-${kind}`}>{LABELS[kind]}{mode ? ` · ${mode}` : ''}</span>
);

export default MoneyBadge;
