import React from 'react';
import Card from '../ui/Card';
import UiEmpty from '../ui/Empty';
import Skeleton from '../ui/Skeleton';
import UiButton from '../ui/Button';
import UiBadge from '../ui/Badge';

/** Settings sections' shared surface: same props the old Sheet had, restyled as a Card. */
export const Sheet = ({ title, meta, actions, children, className = '' }) => (
  <Card title={title} action={actions} className={className}>
    {meta && <p className="-mt-2 mb-3 text-[13px] text-[var(--text-muted)]">{meta}</p>}
    {children}
  </Card>
);

export const Empty = ({ title, detail, action }) => <UiEmpty title={title} body={detail} action={action} />;
export const Ruling = ({ rows }) => <Skeleton rows={rows} />;

export const Stamp = ({ label, tone = 'gain' }) => (
  <span className={`inline-flex items-center min-h-6 rounded-full px-2.5 text-[12px] font-semibold ${tone === 'gain' ? 'bg-[var(--gain-wash)] text-[var(--gain)]' : 'bg-[var(--loss-wash)] text-[var(--loss)]'}`}>
    {label}
  </span>
);

const BTN = { primary: 'primary', danger: 'danger' };
/** Old Button API (variant, size) on the new Button: sizes are fixed at 44px, other variants read as secondary. */
// eslint-disable-next-line no-unused-vars
export const Button = ({ variant = 'primary', size, ...props }) => <UiButton variant={BTN[variant] || 'secondary'} {...props} />;

const BADGE = { success: 'proven', warning: 'unproven', destructive: 'alert', secondary: 'neutral' };
export const Badge = ({ variant, children }) => <UiBadge kind={BADGE[variant] || 'neutral'}>{children}</UiBadge>;
