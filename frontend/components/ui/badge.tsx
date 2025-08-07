import React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-neutral-900 text-neutral-50 dark:bg-neutral-50 dark:text-neutral-900',
        secondary: 'border-transparent bg-neutral-100 text-neutral-900 dark:bg-neutral-800 dark:text-neutral-50',
        outline: 'border-neutral-300 text-neutral-700 dark:border-neutral-600 dark:text-neutral-300',
        success: 'border-transparent bg-success-100 text-success-900 dark:bg-success-900 dark:text-success-100',
        warning: 'border-transparent bg-warning-100 text-warning-900 dark:bg-warning-900 dark:text-warning-100',
        danger: 'border-transparent bg-danger-100 text-danger-900 dark:bg-danger-900 dark:text-danger-100',
        info: 'border-transparent bg-info-100 text-info-900 dark:bg-info-900 dark:text-info-100',
      },
      size: {
        sm: 'px-2 py-0.5 text-xs',
        md: 'px-2.5 py-0.5 text-xs',
        lg: 'px-3 py-1 text-sm',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
  );
}

export { Badge, badgeVariants };