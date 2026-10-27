import React from 'react';

const VARIANTS = {
  primary: 'bg-[var(--accent)] text-[var(--accent-ink)]',
  secondary: 'bg-[var(--surface-2)] text-[var(--text)] border border-[var(--border)]',
  danger: 'bg-[var(--loss)] text-[var(--accent-ink)]',
};

const Button = ({ variant = 'primary', className = '', type = 'button', ...props }) => (
  <button
    type={type}
    className={`tap inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-[12px] text-[15px] font-semibold disabled:opacity-50 ${VARIANTS[variant] || VARIANTS.primary} ${className}`}
    {...props}
  />
);

export default Button;
