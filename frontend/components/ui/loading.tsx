import React from 'react';
import { cn } from '@/lib/utils';

// Spinner component
export interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
}

const Spinner: React.FC<SpinnerProps> = ({ size = 'md', className }) => {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
    xl: 'h-12 w-12',
  };

  return (
    <svg
      className={cn('animate-spin text-current', sizeClasses[size], className)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
};

// Loading overlay for buttons and cards
export interface LoadingOverlayProps {
  children: React.ReactNode;
  loading: boolean;
  spinnerSize?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
}

const LoadingOverlay: React.FC<LoadingOverlayProps> = ({
  children,
  loading,
  spinnerSize = 'md',
  className,
}) => {
  return (
    <div className={cn('relative', className)}>
      {children}
      {loading && (
        <div className="absolute inset-0 bg-white/75 dark:bg-neutral-900/75 backdrop-blur-sm flex items-center justify-center rounded-md">
          <Spinner size={spinnerSize} className="text-primary-500" />
        </div>
      )}
    </div>
  );
};

// Skeleton loading components
export interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'rectangular' | 'circular';
  width?: string | number;
  height?: string | number;
  lines?: number;
}

const LoadingSkeleton: React.FC<SkeletonProps> = ({
  className,
  variant = 'text',
  width,
  height,
  lines = 1,
}) => {
  const getSkeletonClasses = () => {
    const baseClasses = 'animate-pulse bg-neutral-200 dark:bg-neutral-700';
    
    switch (variant) {
      case 'circular':
        return cn(baseClasses, 'rounded-full');
      case 'rectangular':
        return cn(baseClasses, 'rounded-md');
      case 'text':
      default:
        return cn(baseClasses, 'rounded');
    }
  };

  const getDefaultHeight = () => {
    if (height) return typeof height === 'number' ? `${height}px` : height;
    
    switch (variant) {
      case 'text':
        return '1rem';
      case 'rectangular':
        return '3rem';
      case 'circular':
        return '2.5rem';
      default:
        return '1rem';
    }
  };

  const getDefaultWidth = () => {
    if (width) return typeof width === 'number' ? `${width}px` : width;
    
    switch (variant) {
      case 'circular':
        return '2.5rem';
      default:
        return '100%';
    }
  };

  if (variant === 'text' && lines > 1) {
    return (
      <div className={className}>
        {Array.from({ length: lines }).map((_, index) => (
          <div
            key={index}
            className={cn(
              getSkeletonClasses(),
              index < lines - 1 && 'mb-2',
              index === lines - 1 && 'w-3/4' // Last line is shorter
            )}
            style={{
              height: getDefaultHeight(),
              width: index === lines - 1 ? '75%' : getDefaultWidth(),
            }}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(getSkeletonClasses(), className)}
      style={{
        width: getDefaultWidth(),
        height: getDefaultHeight(),
      }}
    />
  );
};

// Table skeleton for data loading
export interface TableSkeletonProps {
  rows?: number;
  columns?: number;
  showHeader?: boolean;
  className?: string;
}

const TableSkeleton: React.FC<TableSkeletonProps> = ({
  rows = 5,
  columns = 4,
  showHeader = true,
  className,
}) => {
  return (
    <div className={cn('w-full', className)}>
      <div className="overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-700">
        {showHeader && (
          <div className="border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-4">
            <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
              {Array.from({ length: columns }).map((_, index) => (
                <LoadingSkeleton key={index} height="1.25rem" width="80%" />
              ))}
            </div>
          </div>
        )}
        <div className="divide-y divide-neutral-200 dark:divide-neutral-700">
          {Array.from({ length: rows }).map((_, rowIndex) => (
            <div key={rowIndex} className="p-4">
              <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
                {Array.from({ length: columns }).map((_, colIndex) => (
                  <LoadingSkeleton 
                    key={colIndex} 
                    height="1rem" 
                    width={colIndex === 0 ? '90%' : Math.random() > 0.5 ? '70%' : '85%'} 
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// Card skeleton
export interface CardSkeletonProps {
  showHeader?: boolean;
  headerLines?: number;
  bodyLines?: number;
  showFooter?: boolean;
  className?: string;
}

const CardSkeleton: React.FC<CardSkeletonProps> = ({
  showHeader = true,
  headerLines = 2,
  bodyLines = 4,
  showFooter = false,
  className,
}) => {
  return (
    <div className={cn('rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-6', className)}>
      {showHeader && (
        <div className="mb-4">
          <LoadingSkeleton height="1.5rem" width="60%" className="mb-2" />
          {headerLines > 1 && <LoadingSkeleton height="1rem" width="40%" />}
        </div>
      )}
      
      <div className="space-y-3">
        {Array.from({ length: bodyLines }).map((_, index) => (
          <LoadingSkeleton 
            key={index} 
            height="1rem" 
            width={index === bodyLines - 1 ? '75%' : '100%'} 
          />
        ))}
      </div>
      
      {showFooter && (
        <div className="mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <div className="flex gap-3">
            <LoadingSkeleton height="2rem" width="5rem" variant="rectangular" />
            <LoadingSkeleton height="2rem" width="5rem" variant="rectangular" />
          </div>
        </div>
      )}
    </div>
  );
};

// Alias for backwards compatibility
export { Spinner as Loading };

export {
  Spinner,
  LoadingOverlay,
  TableSkeleton,
  CardSkeleton,
};