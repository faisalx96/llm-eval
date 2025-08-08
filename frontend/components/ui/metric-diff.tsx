'use client';

import React from 'react';
import { Badge } from './badge';

interface MetricDiffProps {
  metricName: string;
  run1Score: number;
  run2Score: number;
  difference: number;
  percentageChange: number;
  direction: 'better' | 'worse' | 'neutral';
  isSignificant?: boolean;
  pValue?: number;
  confidenceInterval?: [number, number];
  className?: string;
}

export const MetricDiff: React.FC<MetricDiffProps> = ({
  metricName,
  run1Score,
  run2Score,
  difference,
  percentageChange,
  direction,
  isSignificant = false,
  pValue,
  confidenceInterval,
  className = '',
}) => {
  const getDiffColor = () => {
    if (direction === 'better') return 'text-success-600 dark:text-success-400';
    if (direction === 'worse') return 'text-danger-600 dark:text-danger-400';
    return 'text-neutral-600 dark:text-neutral-400';
  };

  const getDiffIcon = () => {
    if (direction === 'better') {
      return (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
        </svg>
      );
    }
    if (direction === 'worse') {
      return (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
        </svg>
      );
    }
    return (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4" />
      </svg>
    );
  };

  const formatScore = (score: number) => {
    if (score >= 0 && score <= 1) {
      return (score * 100).toFixed(1) + '%';
    }
    return score.toFixed(3);
  };

  const formatDifference = (diff: number) => {
    const sign = diff >= 0 ? '+' : '';
    if (Math.abs(diff) >= 0 && Math.abs(diff) <= 1) {
      return `${sign}${(diff * 100).toFixed(1)}pp`;
    }
    return `${sign}${diff.toFixed(3)}`;
  };

  return (
    <div className={`p-4 border border-neutral-200 dark:border-neutral-700 rounded-lg ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-medium text-neutral-900 dark:text-white">
          {metricName}
        </h4>
        {isSignificant && (
          <Badge variant="secondary" size="sm">
            Significant
          </Badge>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4 mb-3">
        <div className="text-center">
          <div className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">Run 1</div>
          <div className="font-mono font-semibold text-neutral-900 dark:text-white">
            {formatScore(run1Score)}
          </div>
        </div>
        
        <div className="text-center">
          <div className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">Run 2</div>
          <div className="font-mono font-semibold text-neutral-900 dark:text-white">
            {formatScore(run2Score)}
          </div>
        </div>
        
        <div className="text-center">
          <div className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">Change</div>
          <div className={`font-mono font-semibold flex items-center justify-center gap-1 ${getDiffColor()}`}>
            {getDiffIcon()}
            {formatDifference(difference)}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
        <span>{percentageChange >= 0 ? '+' : ''}{percentageChange.toFixed(1)}% change</span>
        {pValue !== undefined && (
          <span>p = {pValue.toFixed(4)}</span>
        )}
      </div>

      {confidenceInterval && (
        <div className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
          95% CI: [{confidenceInterval[0].toFixed(3)}, {confidenceInterval[1].toFixed(3)}]
        </div>
      )}
    </div>
  );
};