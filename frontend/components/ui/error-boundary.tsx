'use client';

import React from 'react';
import { Button } from './button';
import { Card } from './card';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ComponentType<ErrorFallbackProps>;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface ErrorFallbackProps {
  error: Error;
  resetError: () => void;
  errorInfo?: React.ErrorInfo;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({
      error,
      errorInfo,
    });

    // Log error to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('ErrorBoundary caught an error:', error, errorInfo);
    }

    // Call onError callback if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  resetError = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      const FallbackComponent = this.props.fallback || DefaultErrorFallback;
      return (
        <FallbackComponent
          error={this.state.error}
          errorInfo={this.state.errorInfo || undefined}
          resetError={this.resetError}
        />
      );
    }

    return this.props.children;
  }
}

const DefaultErrorFallback: React.FC<ErrorFallbackProps> = ({ error, resetError, errorInfo }) => {
  const isDevelopment = process.env.NODE_ENV === 'development';

  return (
    <Card className="p-6 m-4">
      <div className="flex items-start space-x-4">
        <div className="flex-shrink-0">
          <svg className="w-6 h-6 text-destructive-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.268 13.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-semibold text-destructive-700 dark:text-destructive-300 mb-2">
            Something went wrong
          </h3>
          <p className="text-neutral-600 dark:text-neutral-300 mb-4">
            An unexpected error occurred. Please try refreshing the page or contact support if the problem persists.
          </p>
          
          {isDevelopment && (
            <details className="mb-4">
              <summary className="cursor-pointer text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Error Details (Development Mode)
              </summary>
              <div className="bg-neutral-100 dark:bg-neutral-800 rounded-lg p-4 overflow-auto">
                <pre className="text-xs text-destructive-600 dark:text-destructive-400 whitespace-pre-wrap">
                  <strong>Error:</strong> {error.message}
                  {'\n\n'}
                  <strong>Stack:</strong> {error.stack}
                  {errorInfo && (
                    <>
                      {'\n\n'}
                      <strong>Component Stack:</strong> {errorInfo.componentStack}
                    </>
                  )}
                </pre>
              </div>
            </details>
          )}

          <div className="flex flex-col sm:flex-row gap-3">
            <Button onClick={resetError} variant="default" size="md">
              Try Again
            </Button>
            <Button 
              onClick={() => window.location.reload()} 
              variant="outline" 
              size="md"
            >
              Reload Page
            </Button>
            <Button 
              onClick={() => window.history.back()} 
              variant="ghost" 
              size="md"
            >
              Go Back
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
};

// Higher-order component wrapper for easier use
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  errorFallback?: React.ComponentType<ErrorFallbackProps>,
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
) {
  const WrappedComponent = (props: P) => (
    <ErrorBoundary fallback={errorFallback} onError={onError}>
      <Component {...props} />
    </ErrorBoundary>
  );

  WrappedComponent.displayName = `withErrorBoundary(${Component.displayName || Component.name})`;
  return WrappedComponent;
}

// Specialized error boundaries for different sections

export const ChartErrorBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ErrorBoundary
    fallback={({ error, resetError }) => (
      <div className="bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-6 text-center">
        <svg className="w-12 h-12 text-neutral-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
          Chart Error
        </h3>
        <p className="text-neutral-600 dark:text-neutral-300 mb-4">
          Unable to render chart visualization.
        </p>
        <Button onClick={resetError} variant="outline" size="sm">
          Retry Chart
        </Button>
      </div>
    )}
  >
    {children}
  </ErrorBoundary>
);

export const TableErrorBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ErrorBoundary
    fallback={({ error, resetError }) => (
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6 text-center">
        <svg className="w-12 h-12 text-neutral-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5a2 2 0 012-2h4a2 2 0 012 2v2H8V5z" />
        </svg>
        <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
          Table Error
        </h3>
        <p className="text-neutral-600 dark:text-neutral-300 mb-4">
          Unable to load table data.
        </p>
        <Button onClick={resetError} variant="outline" size="sm">
          Retry Table
        </Button>
      </div>
    )}
  >
    {children}
  </ErrorBoundary>
);