import React from 'react';

const LABELS = { mine: 'Mine', ai: 'AI', paper: 'Paper' };

/** Whose money a figure is: the user's own account, the AI account, or practice. */
const MoneyBadge = ({ kind }) => <span className={`badge-${kind}`}>{LABELS[kind]}</span>;

export default MoneyBadge;
