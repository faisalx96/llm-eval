'use client';

import React, { useMemo } from 'react';
import { Card } from './card';
import { RunComparison } from '../../types';

interface ComparisonChartProps {
  comparison: RunComparison;
  chartType?: 'bar' | 'radar';
  className?: string;
}

export const ComparisonChart: React.FC<ComparisonChartProps> = ({
  comparison,
  chartType = 'bar',
  className = '',
}) => {
  const chartData = useMemo(() => {
    const metrics = comparison.comparison.metrics;
    const metricNames = Object.keys(metrics);

    const run1Data = metricNames.map(name => ({
      metric: name,
      score: metrics[name].run1_score,
      label: comparison.run1.name,
    }));

    const run2Data = metricNames.map(name => ({
      metric: name,
      score: metrics[name].run2_score,
      label: comparison.run2.name,
    }));

    return { run1Data, run2Data, metricNames };
  }, [comparison]);

  const maxScore = useMemo(() => {
    const allScores = [
      ...chartData.run1Data.map(d => d.score),
      ...chartData.run2Data.map(d => d.score),
    ];
    return Math.max(...allScores);
  }, [chartData]);

  const formatScore = (score: number) => {
    if (score >= 0 && score <= 1) {
      return (score * 100).toFixed(1) + '%';
    }
    return score.toFixed(3);
  };

  const getBarWidth = (score: number) => {
    return `${(score / maxScore) * 100}%`;
  };

  const getDiffColor = (direction: 'better' | 'worse' | 'neutral') => {
    if (direction === 'better') return 'bg-success-100 dark:bg-success-900/30';
    if (direction === 'worse') return 'bg-danger-100 dark:bg-danger-900/30';
    return 'bg-neutral-100 dark:bg-neutral-800';
  };

  if (chartType === 'bar') {
    return (
      <Card className={`p-6 ${className}`}>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-6">
          Metric Comparison
        </h3>

        <div className="space-y-6">
          {chartData.metricNames.map((metricName) => {
            const metricData = comparison.comparison.metrics[metricName];
            const run1Score = metricData.run1_score;
            const run2Score = metricData.run2_score;
            const direction = metricData.improvement_direction;

            return (
              <div key={metricName} className={`p-4 rounded-lg ${getDiffColor(direction)}`}>
                <div className="flex items-center justify-between mb-3">
                  <h4 className="font-medium text-neutral-900 dark:text-white">
                    {metricName}
                  </h4>
                  <div className="text-sm font-mono">
                    {formatScore(Math.abs(metricData.difference))} diff
                  </div>
                </div>

                <div className="space-y-3">
                  {/* Run 1 bar */}
                  <div>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="text-neutral-700 dark:text-neutral-300">
                        {comparison.run1.name}
                      </span>
                      <span className="font-mono font-medium">
                        {formatScore(run1Score)}
                      </span>
                    </div>
                    <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-3">
                      <div
                        className="bg-primary-500 h-3 rounded-full transition-all duration-300"
                        style={{ width: getBarWidth(run1Score) }}
                      />
                    </div>
                  </div>

                  {/* Run 2 bar */}
                  <div>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="text-neutral-700 dark:text-neutral-300">
                        {comparison.run2.name}
                      </span>
                      <span className="font-mono font-medium">
                        {formatScore(run2Score)}
                      </span>
                    </div>
                    <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-3">
                      <div
                        className="bg-secondary-500 h-3 rounded-full transition-all duration-300"
                        style={{ width: getBarWidth(run2Score) }}
                      />
                    </div>
                  </div>
                </div>

                {/* Statistical significance indicator */}
                {comparison.comparison.statistical_analysis[metricName]?.is_significant && (
                  <div className="mt-2 text-xs text-success-600 dark:text-success-400 flex items-center gap-1">
                    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    Statistically significant
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <div className="flex items-center justify-between text-sm text-neutral-600 dark:text-neutral-400">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-primary-500 rounded"></div>
                <span>{comparison.run1.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-secondary-500 rounded"></div>
                <span>{comparison.run2.name}</span>
              </div>
            </div>
            <div>
              Winner: <span className="font-medium">
                {comparison.comparison.overall_performance.winner === 'run1'
                  ? comparison.run1.name
                  : comparison.comparison.overall_performance.winner === 'run2'
                  ? comparison.run2.name
                  : 'Tie'
                }
              </span>
            </div>
          </div>
        </div>
      </Card>
    );
  }

  // Radar chart implementation would go here for the future
  return (
    <Card className={`p-6 ${className}`}>
      <div className="text-center py-12">
        <div className="text-neutral-500 dark:text-neutral-400">
          Radar chart view coming soon
        </div>
      </div>
    </Card>
  );
};
