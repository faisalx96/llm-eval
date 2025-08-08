'use client';

import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { SkeletonBox } from './skeleton';

// Dynamic import to avoid SSR issues with Plotly
const Plot = dynamic(() => import('react-plotly.js'), { 
  ssr: false,
  loading: () => <SkeletonBox className="h-80 w-full" />
});

type ChartType = 'bar' | 'distribution';

interface MetricChartProps {
  data: {
    metric: string;
    score: number;
    passed: number;
    failed: number;
  }[];
  showInteractiveCharts?: boolean;
}

export const MetricChart: React.FC<MetricChartProps> = ({ 
  data, 
  showInteractiveCharts = true 
}) => {
  const [chartType, setChartType] = useState<ChartType>('bar');

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-4 text-neutral-500 dark:text-neutral-400">
        No metric data available
      </div>
    );
  }

  const maxScore = Math.max(...data.map(d => d.score));
  const maxItems = Math.max(...data.map(d => d.passed + d.failed));

  // Interactive Plotly charts
  const renderInteractiveChart = () => {
    if (chartType === 'bar') {
      return (
        <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-medium text-neutral-900 dark:text-white">
              Metrics Score Comparison
            </h4>
            <div className="flex gap-2">
              <button
                onClick={() => setChartType('bar')}
                className={`px-3 py-1 text-sm rounded ${
                  (chartType as string) === 'bar'
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
                    : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
                }`}
              >
                Bar Chart
              </button>
              <button
                onClick={() => setChartType('distribution')}
                className={`px-3 py-1 text-sm rounded ${
                  (chartType as string) === 'distribution'
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
                    : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
                }`}
              >
                Distribution
              </button>
            </div>
          </div>
          <Plot
            data={[
              {
                x: data.map(d => d.metric.replace(/_/g, ' ')),
                y: data.map(d => d.score * 100),
                type: 'bar',
                marker: {
                  color: data.map(d => 
                    d.score >= 0.8 ? '#22c55e' : 
                    d.score >= 0.6 ? '#f59e0b' : 
                    '#ef4444'
                  ),
                },
                text: data.map(d => `${(d.score * 100).toFixed(1)}%`),
                textposition: 'auto',
              },
            ]}
            layout={{
              xaxis: { 
                title: 'Metrics',
                tickangle: -45,
              },
              yaxis: { 
                title: 'Score (%)',
                range: [0, 100]
              },
              margin: { t: 20, r: 20, b: 80, l: 60 },
              plot_bgcolor: 'transparent',
              paper_bgcolor: 'transparent',
              font: { size: 12 },
              showlegend: false,
            }}
            config={{
              displayModeBar: false,
              responsive: true,
            }}
            style={{ width: '100%', height: '300px' }}
          />
        </div>
      );
    } else {
      // Pass/Fail Distribution Chart
      const totalPassed = data.reduce((sum, d) => sum + d.passed, 0);
      const totalFailed = data.reduce((sum, d) => sum + d.failed, 0);

      return (
        <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-medium text-neutral-900 dark:text-white">
              Pass/Fail Distribution
            </h4>
            <div className="flex gap-2">
              <button
                onClick={() => setChartType('bar')}
                className={`px-3 py-1 text-sm rounded ${
                  (chartType as string) === 'bar'
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
                    : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
                }`}
              >
                Bar Chart
              </button>
              <button
                onClick={() => setChartType('distribution')}
                className={`px-3 py-1 text-sm rounded ${
                  (chartType as string) === 'distribution'
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
                    : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
                }`}
              >
                Distribution
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Plot
              data={[
                {
                  values: [totalPassed, totalFailed],
                  labels: ['Passed', 'Failed'],
                  type: 'pie',
                  marker: {
                    colors: ['#22c55e', '#ef4444'],
                  },
                  textinfo: 'label+percent',
                  textposition: 'outside',
                },
              ]}
              layout={{
                title: { text: 'Overall Distribution' },
                margin: { t: 40, r: 20, b: 20, l: 20 },
                plot_bgcolor: 'transparent',
                paper_bgcolor: 'transparent',
                font: { size: 12 },
                showlegend: false,
              }}
              config={{
                displayModeBar: false,
                responsive: true,
              }}
              style={{ width: '100%', height: '250px' }}
            />
            <Plot
              data={[
                {
                  x: data.map(d => d.metric.replace(/_/g, ' ')),
                  y: data.map(d => d.passed),
                  name: 'Passed',
                  type: 'bar',
                  marker: { color: '#22c55e' },
                },
                {
                  x: data.map(d => d.metric.replace(/_/g, ' ')),
                  y: data.map(d => d.failed),
                  name: 'Failed',
                  type: 'bar',
                  marker: { color: '#ef4444' },
                },
              ]}
              layout={{
                title: { text: 'By Metric' },
                barmode: 'stack',
                xaxis: { 
                  title: 'Metrics',
                  tickangle: -45,
                },
                yaxis: { title: 'Count' },
                margin: { t: 40, r: 20, b: 80, l: 60 },
                plot_bgcolor: 'transparent',
                paper_bgcolor: 'transparent',
                font: { size: 12 },
                legend: {
                  x: 1,
                  xanchor: 'right',
                  y: 1,
                },
              }}
              config={{
                displayModeBar: false,
                responsive: true,
              }}
              style={{ width: '100%', height: '250px' }}
            />
          </div>
        </div>
      );
    }
  };

  // Fallback simple visualization
  const renderSimpleChart = () => (
    <div className="space-y-4">
      {data.map((item, index) => {
        const total = item.passed + item.failed;
        const passedPercentage = total > 0 ? (item.passed / total) * 100 : 0;
        const scorePercentage = (item.score / maxScore) * 100;
        
        return (
          <div key={item.metric} className="bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-medium text-neutral-900 dark:text-white capitalize">
                {item.metric.replace(/_/g, ' ')}
              </h4>
              <div className="flex items-center gap-4">
                <span className="text-sm text-neutral-600 dark:text-neutral-300">
                  {(item.score * 100).toFixed(1)}%
                </span>
                <span className="text-xs text-neutral-500 dark:text-neutral-400">
                  {item.passed}/{total}
                </span>
              </div>
            </div>
            
            {/* Score Bar */}
            <div className="mb-2">
              <div className="flex items-center justify-between text-xs text-neutral-600 dark:text-neutral-300 mb-1">
                <span>Score</span>
                <span>{(item.score * 100).toFixed(1)}%</span>
              </div>
              <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                <div 
                  className={`h-2 rounded-full transition-all duration-500 ${
                    item.score >= 0.8 ? 'bg-success-500' :
                    item.score >= 0.6 ? 'bg-warning-500' :
                    'bg-destructive-500'
                  }`}
                  style={{ width: `${scorePercentage}%` }}
                />
              </div>
            </div>

            {/* Pass/Fail Distribution */}
            {total > 0 && (
              <div>
                <div className="flex items-center justify-between text-xs text-neutral-600 dark:text-neutral-300 mb-1">
                  <span>Pass Rate</span>
                  <span>{passedPercentage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                  <div 
                    className="h-2 bg-success-500 rounded-full transition-all duration-500"
                    style={{ width: `${passedPercentage}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                  <span className="text-success-600 dark:text-success-400">
                    ✓ {item.passed} passed
                  </span>
                  <span className="text-destructive-600 dark:text-destructive-400">
                    ✗ {item.failed} failed
                  </span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <div>
      {showInteractiveCharts ? renderInteractiveChart() : renderSimpleChart()}
      {showInteractiveCharts && renderSimpleChart()}
    </div>
  );
};