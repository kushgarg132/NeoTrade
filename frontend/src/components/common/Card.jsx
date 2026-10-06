import React from 'react';
import { cn } from '../../utils/cn';

/**
 * A sheet of the note. Square corners, a printed border, a ruled header band.
 * Named Card for the imports that already exist; it is a sheet everywhere else.
 */
const Card = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('sheet', className)} {...props} />
));
Card.displayName = 'Card';

const CardHeader = React.forwardRef(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('px-4 py-3 border-b border-[var(--rule)] bg-[var(--paper-sunk)]', className)}
    {...props}
  />
));
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef(({ className, ...props }, ref) => (
  <h3 ref={ref} className={cn('field-label text-[var(--ink)]', className)} {...props} />
));
CardTitle.displayName = 'CardTitle';

const CardContent = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('p-4', className)} {...props} />
));
CardContent.displayName = 'CardContent';

export { Card, CardHeader, CardTitle, CardContent };
