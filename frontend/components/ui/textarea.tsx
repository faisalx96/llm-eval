import React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// Counter for generating stable IDs
let textareaIdCounter = 0;

const textareaVariants = cva(
  'flex min-h-[80px] w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm ring-offset-white placeholder:text-neutral-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-600 dark:bg-neutral-800 dark:ring-offset-neutral-800 dark:placeholder:text-neutral-400',
  {
    variants: {
      variant: {
        default: '',
        error: 'border-danger-500 focus-visible:ring-danger-500',
        success: 'border-success-500 focus-visible:ring-success-500',
      },
      size: {
        sm: 'min-h-[60px] px-2 py-1 text-xs',
        md: 'min-h-[80px] px-3 py-2 text-sm',
        lg: 'min-h-[120px] px-4 py-3 text-base',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
);

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement>,
    VariantProps<typeof textareaVariants> {
  error?: string;
  label?: string;
  hint?: string;
  maxLength?: number;
  showCharCount?: boolean;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ 
    className, 
    variant, 
    size,
    error,
    label,
    hint,
    maxLength,
    showCharCount = false,
    id,
    value,
    onChange,
    ...props 
  }, ref) => {
    // Use React.useId for stable ID generation, fallback to counter for older React versions
    const reactId = React.useId?.() || `textarea-${++textareaIdCounter}`;
    const textareaId = id || reactId;
    const effectiveVariant = error ? 'error' : variant;
    const currentLength = typeof value === 'string' ? value.length : 0;

    return (
      <div className="w-full">
        {label && (
          <label
            htmlFor={textareaId}
            className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <textarea
            id={textareaId}
            className={cn(textareaVariants({ variant: effectiveVariant, size }), className)}
            ref={ref}
            value={value}
            onChange={onChange}
            maxLength={maxLength}
            {...props}
          />
          {showCharCount && maxLength && (
            <div className="absolute bottom-2 right-2 text-xs text-neutral-400 bg-white dark:bg-neutral-800 px-1 rounded">
              {currentLength}/{maxLength}
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

Textarea.displayName = 'Textarea';

export { Textarea, textareaVariants };