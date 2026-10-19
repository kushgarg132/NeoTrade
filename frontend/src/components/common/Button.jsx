import React from 'react';
import { cn } from '../../utils/cn';

const VARIANTS = {
  primary: 'bg-[var(--accent)] text-[var(--surface)] border-transparent',
  secondary: 'bg-[var(--surface-2)] text-[var(--text)] border-[var(--border)]',
  outline: 'bg-transparent text-[var(--text)] border-[var(--border)]',
  glass: 'bg-transparent text-[var(--text)] border-[var(--border)]',
  ghost: 'bg-transparent text-[var(--text-muted)] border-transparent',
  danger: 'bg-[var(--loss)] text-[var(--surface)] border-transparent',
  approve: 'bg-[var(--gain)] text-[var(--surface)] border-transparent',
};

// Touch targets stay 44px; `sm` is only a little tighter in width.
const SIZES = {
  sm: 'min-h-11 px-3 text-[14px]',
  md: 'min-h-11 px-4 text-[15px]',
  lg: 'min-h-12 px-6 text-[15px]',
  icon: 'min-h-11 min-w-11',
};

const Button = React.forwardRef(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-[12px] border font-semibold transition-colors',
        'disabled:opacity-50 disabled:pointer-events-none',
        VARIANTS[variant] || VARIANTS.primary,
        SIZES[size] || SIZES.md,
        className
      )}
      {...props}
    />
  )
);
Button.displayName = 'Button';

export { Button };
