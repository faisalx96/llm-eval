'use client';

import React, { useState } from 'react';
import { Card } from './card';
import { Button } from './button';
import { Badge } from './badge';
import { Input } from './input';
import { Modal } from './modal';
import { MetricInfo, MetricSelection } from '@/types';
import { cn } from '@/lib/utils';

interface MetricCardProps {
  metric: MetricInfo;
  isSelected: boolean;
  selection?: MetricSelection;
  onSelect: (metricId: string, parameters?: Record<string, any>) => void;
  onDeselect: (metricId: string) => void;
  onParametersChange?: (metricId: string, parameters: Record<string, any>) => void;
  compatibility?: { compatible: boolean; issues: string[] };
  className?: string;
}

export function MetricCard({
  metric,
  isSelected,
  selection,
  onSelect,
  onDeselect,
  onParametersChange,
  compatibility,
  className
}: MetricCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [showParameters, setShowParameters] = useState(false);
  const [parameters, setParameters] = useState<Record<string, any>>(selection?.parameters || {});

  const getCategoryColor = (category: string) => {
    const colors = {
      accuracy: 'bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
      semantic: 'bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-300',
      safety: 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300',
      performance: 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300',
      custom: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300'
    };
    return colors[category as keyof typeof colors] || colors.custom;
  };

  const getCompatibilityBadge = () => {
    if (!compatibility) return null;
    
    if (compatibility.compatible) {
      return (
        <Badge variant="success" size="sm" title="Compatible with selected dataset">
          <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Compatible
        </Badge>
      );
    } else {
      return (
        <Badge variant="danger" size="sm" title={compatibility.issues.join(', ')}>
          <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          Incompatible
        </Badge>
      );
    }
  };

  const handleSelect = () => {
    if (compatibility && !compatibility.compatible) return;
    
    if (metric.parameters && Object.keys(metric.parameters).length > 0) {
      setShowParameters(true);
    } else {
      onSelect(metric.id);
    }
  };

  const handleParametersSubmit = () => {
    onSelect(metric.id, parameters);
    setShowParameters(false);
  };

  const handleParameterChange = (key: string, value: any) => {
    const newParameters = { ...parameters, [key]: value };
    setParameters(newParameters);
    
    if (isSelected && onParametersChange) {
      onParametersChange(metric.id, newParameters);
    }
  };

  const renderParameterInput = (key: string, config: any) => {
    const value = parameters[key] ?? config.default;
    
    switch (config.type) {
      case 'number':
        return (
          <Input
            type="number"
            value={value || ''}
            onChange={(e) => handleParameterChange(key, parseFloat(e.target.value) || config.default)}
            placeholder={config.default?.toString()}
            min={config.min}
            max={config.max}
            step={config.step}
          />
        );
      case 'boolean':
        return (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={value ?? config.default}
              onChange={(e) => handleParameterChange(key, e.target.checked)}
              className="rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
            />
            <span className="text-sm">{config.description || key}</span>
          </label>
        );
      case 'string':
      default:
        return (
          <Input
            type="text"
            value={value || ''}
            onChange={(e) => handleParameterChange(key, e.target.value)}
            placeholder={config.default?.toString() || config.description}
          />
        );
    }
  };

  return (
    <>
      <Card
        className={cn(
          'p-4 transition-all duration-200 cursor-pointer',
          'hover:shadow-md hover:border-primary-200 dark:hover:border-primary-800',
          isSelected && 'ring-2 ring-primary-500 border-primary-500 bg-primary-50 dark:bg-primary-900/20',
          compatibility && !compatibility.compatible && 'opacity-60 cursor-not-allowed',
          className
        )}
        onClick={compatibility && !compatibility.compatible ? undefined : handleSelect}
      >
        <div className="space-y-3">
          {/* Header */}
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-medium text-neutral-900 dark:text-white truncate">
                  {metric.display_name}
                </h3>
                {metric.is_custom && (
                  <Badge variant="neutral" size="sm">
                    Custom
                  </Badge>
                )}
              </div>
              <p className="text-sm text-neutral-500 dark:text-neutral-400 line-clamp-2">
                {metric.description}
              </p>
            </div>
            
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowDetails(true);
              }}
              className="ml-2 p-1 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 rounded transition-colors"
              title="View details"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
          </div>

          {/* Badges */}
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={getCategoryColor(metric.category)} size="sm">
              {metric.category}
            </Badge>
            {getCompatibilityBadge()}
            {isSelected && (
              <Badge variant="primary" size="sm">
                Selected
              </Badge>
            )}
          </div>

          {/* Compatible tasks */}
          {metric.compatible_tasks.length > 0 && (
            <div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">
                Compatible with:
              </p>
              <div className="flex items-center gap-1 flex-wrap">
                {metric.compatible_tasks.slice(0, 3).map(task => (
                  <Badge key={task} variant="neutral" size="sm" className="text-xs">
                    {task}
                  </Badge>
                ))}
                {metric.compatible_tasks.length > 3 && (
                  <span className="text-xs text-neutral-400">
                    +{metric.compatible_tasks.length - 3} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-2 border-t border-neutral-100 dark:border-neutral-700">
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              {metric.requirements.length > 0 && (
                <span>Requires: {metric.requirements.slice(0, 2).join(', ')}</span>
              )}
            </div>
            
            {isSelected ? (
              <Button
                variant="danger"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeselect(metric.id);
                }}
              >
                Remove
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                disabled={compatibility && !compatibility.compatible}
                onClick={(e) => {
                  e.stopPropagation();
                  handleSelect();
                }}
              >
                Add Metric
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Details Modal */}
      <Modal
        isOpen={showDetails}
        onClose={() => setShowDetails(false)}
        title={metric.display_name}
        size="lg"
      >
        <div className="space-y-6">
          <div>
            <h3 className="font-medium text-neutral-900 dark:text-white mb-2">Description</h3>
            <p className="text-neutral-700 dark:text-neutral-300">{metric.description}</p>
          </div>

          {metric.requirements.length > 0 && (
            <div>
              <h3 className="font-medium text-neutral-900 dark:text-white mb-2">Requirements</h3>
              <ul className="list-disc list-inside space-y-1 text-sm text-neutral-700 dark:text-neutral-300">
                {metric.requirements.map((req, index) => (
                  <li key={index}>{req}</li>
                ))}
              </ul>
            </div>
          )}

          {metric.examples && metric.examples.length > 0 && (
            <div>
              <h3 className="font-medium text-neutral-900 dark:text-white mb-2">Examples</h3>
              <div className="space-y-3">
                {metric.examples.map((example, index) => (
                  <div key={index} className="bg-neutral-50 dark:bg-neutral-800 rounded p-3 text-sm">
                    <div className="grid grid-cols-2 gap-4 mb-2">
                      <div>
                        <span className="font-medium">Input:</span> {JSON.stringify(example.input)}
                      </div>
                      <div>
                        <span className="font-medium">Output:</span> {JSON.stringify(example.output)}
                      </div>
                    </div>
                    <div className="mb-2">
                      <span className="font-medium">Score:</span> {example.score}
                    </div>
                    <div>
                      <span className="font-medium">Explanation:</span> {example.explanation}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end">
            <Button variant="neutral" onClick={() => setShowDetails(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* Parameters Modal */}
      <Modal
        isOpen={showParameters}
        onClose={() => setShowParameters(false)}
        title={`Configure ${metric.display_name}`}
        size="md"
      >
        <div className="space-y-6">
          <p className="text-neutral-700 dark:text-neutral-300">
            This metric requires configuration. Please set the parameters below.
          </p>

          {metric.parameters && (
            <div className="space-y-4">
              {Object.entries(metric.parameters).map(([key, config]) => (
                <div key={key}>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    {config.label || key}
                    {config.required && <span className="text-red-500 ml-1">*</span>}
                  </label>
                  {renderParameterInput(key, config)}
                  {config.description && (
                    <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                      {config.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <Button variant="neutral" onClick={() => setShowParameters(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleParametersSubmit}>
              Add Metric
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}