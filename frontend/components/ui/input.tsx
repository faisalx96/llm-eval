import React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// Counter for generating stable IDs
let inputIdCounter = 0;

const inputVariants = cva(
  'flex w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm ring-offset-white file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-neutral-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-600 dark:bg-neutral-800 dark:ring-offset-neutral-800 dark:placeholder:text-neutral-400',
  {
    variants: {
      variant: {
        default: '',
        error: 'border-danger-500 focus-visible:ring-danger-500',
        success: 'border-success-500 focus-visible:ring-success-500',
      },
      size: {
        sm: 'h-8 px-2 text-xs',
        md: 'h-10 px-3 text-sm',
        lg: 'h-12 px-4 text-base',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
);

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'>,
    VariantProps<typeof inputVariants> {
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  error?: string;
  label?: string;
  hint?: string;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ 
    className, 
    variant, 
    size, 
    type = 'text',
    leftIcon,
    rightIcon,
    error,
    label,
    hint,
    id,
    ...props 
  }, ref) => {
    // Use React.useId for stable ID generation, fallback to counter for older React versions
    const reactId = React.useId?.() || `input-${++inputIdCounter}`;
    const inputId = id || reactId;
    const effectiveVariant = error ? 'error' : variant;

    return (
      <div className="w-full">
        {label && (
          <label
            htmlFor={inputId}
            className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <div className="text-neutral-400 text-sm">
                {leftIcon}
              </div>
            </div>
          )}
          <input
            id={inputId}
            type={type}
            className={cn(
              inputVariants({ variant: effectiveVariant, size }),
              leftIcon && 'pl-10',
              rightIcon && 'pr-10',
              className
            )}
            ref={ref}
            {...props}
          />
          {rightIcon && (
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
              <div className="text-neutral-400 text-sm">
                {rightIcon}
              </div>
            </div>
          )}
        </div>
        {error && (
          <p className="mt-1 text-sm text-danger-600 dark:text-danger-400">
            {error}
          </p>
        )}
        {hint && !error && (
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            {hint}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';

export { Input, inputVariants };