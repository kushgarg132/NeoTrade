import React from 'react';
import { cn } from '../../utils/cn';

/** A small status pill. */
const VARIANTS = {
  default: 'bg-[var(--surface-2)] text-[var(--text)]',
  secondary: 'bg-[var(--surface-2)] text-[var(--text-muted)]',
  outline: 'bg-[var(--surface-2)] text-[var(--text-muted)]',
  neutral: 'bg-[var(--surface-2)] text-[var(--text-muted)]',
  success: 'bg-[var(--gain-wash)] text-[var(--gain)]',
  destructive: 'bg-[var(--loss-wash)] text-[var(--loss)]',
  warning: 'bg-[var(--surface-2)] text-[var(--warn)]',
  stamp: 'bg-[var(--accent-soft)] text-[var(--accent)]',
};

const Badge = ({ className, variant = 'default', ...props }) => (
  <span
    className={cn('inline-flex items-center gap-1 rounded-full px-2 min-h-6 text-[12px] font-semibold', VARIANTS[variant] || VARIANTS.default, className)}
    {...props}
  />
);

export { Badge };
