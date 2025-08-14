'use client';

import React, { useState } from 'react';
import { Card } from './card';
import { Button } from './button';
import { Badge } from './badge';
import { Modal } from './modal';
import { EvaluationTemplate } from '@/types';
import { cn } from '@/lib/utils';

interface TemplateCardProps {
  template: EvaluationTemplate;
  onSelect?: (template: EvaluationTemplate) => void;
  isSelected?: boolean;
  selectionMode?: boolean;
  className?: string;
}

export function TemplateCard({
  template,
  onSelect,
  isSelected = false,
  selectionMode = false,
  className
}: TemplateCardProps) {
  const [showDetails, setShowDetails] = useState(false);

  const getCategoryColor = (category: string) => {
    const colors = {
      qa: 'bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
      summarization: 'bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-300',
      classification: 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300',
      general: 'bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-300',
      custom: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300'
    };
    return colors[category as keyof typeof colors] || colors.custom;
  };

  const getCategoryIcon = (category: string) => {
    const icons = {
      qa: '❓',
      summarization: '📝',
      classification: '🏷️',
      general: '⚙️',
      custom: '🔧'
    };
    return icons[category as keyof typeof icons] || icons.custom;
  };

  const getPopularityText = (score: number) => {
    if (score >= 0.8) return 'Very Popular';
    if (score >= 0.6) return 'Popular';
    if (score >= 0.4) return 'Growing';
    return 'New';
  };

  const handleCardClick = () => {
    if (selectionMode && onSelect) {
      onSelect(template);
    } else {
      setShowDetails(true);
    }
  };

  return (
    <>
      <Card
        className={cn(
          'p-6 cursor-pointer transition-all duration-200',
          'hover:shadow-lg hover:border-primary-200 dark:hover:border-primary-800',
          isSelected && 'ring-2 ring-primary-500 border-primary-500 bg-primary-50 dark:bg-primary-900/20',
          className
        )}
        onClick={handleCardClick}
      >
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-2xl" title={template.category}>
                  {getCategoryIcon(template.category)}
                </span>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-neutral-900 dark:text-white truncate">
                    {template.display_name}
                  </h3>
                  {template.author && (
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">
                      by {template.author}
                    </p>
                  )}
                </div>
              </div>
              <p className="text-sm text-neutral-600 dark:text-neutral-300 line-clamp-2">
                {template.description}
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
            <Badge className={getCategoryColor(template.category)} size="sm">
              {template.category}
            </Badge>
            {template.popularity_score > 0.6 && (
              <Badge variant="success" size="sm">
                {getPopularityText(template.popularity_score)}
              </Badge>
            )}
            {isSelected && (
              <Badge variant="primary" size="sm">
                Selected
              </Badge>
            )}
          </div>

          {/* Metrics */}
          <div>
            <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-2">
              Included Metrics ({template.metrics.length})
            </p>
            <div className="flex items-center gap-1 flex-wrap">
              {template.metrics.slice(0, 4).map(metric => (
                <Badge key={metric} variant="neutral" size="sm" className="text-xs">
                  {metric}
                </Badge>
              ))}
              {template.metrics.length > 4 && (
                <span className="text-xs text-neutral-400">
                  +{template.metrics.length - 4} more
                </span>
              )}
            </div>
          </div>

          {/* Use Cases */}
          {template.use_cases.length > 0 && (
            <div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-2">
                Use Cases
              </p>
              <div className="flex items-center gap-1 flex-wrap">
                {template.use_cases.slice(0, 3).map(useCase => (
                  <Badge key={useCase} variant="neutral" size="sm" className="text-xs">
                    {useCase}
                  </Badge>
                ))}
                {template.use_cases.length > 3 && (
                  <span className="text-xs text-neutral-400">
                    +{template.use_cases.length - 3} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Tags */}
          {template.tags.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap pt-2 border-t border-neutral-100 dark:border-neutral-700">
              {template.tags.slice(0, 3).map(tag => (
                <span key={tag} className="text-xs text-neutral-500 dark:text-neutral-400">
                  #{tag}
                </span>
              ))}
              {template.tags.length > 3 && (
                <span className="text-xs text-neutral-400">
                  +{template.tags.length - 3}
                </span>
              )}
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between pt-4 border-t border-neutral-100 dark:border-neutral-700">
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              {template.created_at && new Date(template.created_at).toLocaleDateString()}
            </div>
            
            {selectionMode ? (
              <Button
                variant={isSelected ? "danger" : "primary"}
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect?.(template);
                }}
              >
                {isSelected ? 'Deselect' : 'Select Template'}
              </Button>
            ) : (
              <Button
                variant="neutral"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowDetails(true);
                }}
              >
                View Details
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Details Modal */}
      <Modal
        isOpen={showDetails}
        onClose={() => setShowDetails(false)}
        title={template.display_name}
        size="lg"
      >
        <div className="space-y-6">
          {/* Basic Info */}
          <div>
            <div className="flex items-center gap-3 mb-4">
              <span className="text-3xl">{getCategoryIcon(template.category)}</span>
              <div>
                <h3 className="text-xl font-semibold text-neutral-900 dark:text-white">
                  {template.display_name}
                </h3>
                {template.author && (
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Created by {template.author}
                  </p>
                )}
              </div>
            </div>
            
            <p className="text-neutral-700 dark:text-neutral-300 mb-4">
              {template.description}
            </p>

            <div className="flex items-center gap-2 flex-wrap">
              <Badge className={getCategoryColor(template.category)}>
                {template.category}
              </Badge>
              {template.popularity_score > 0.6 && (
                <Badge variant="success">
                  {getPopularityText(template.popularity_score)}
                </Badge>
              )}
            </div>
          </div>

          {/* Metrics */}
          <div>
            <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
              Included Metrics ({template.metrics.length})
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {template.metrics.map(metric => (
                <Badge key={metric} variant="neutral" className="justify-center">
                  {metric}
                </Badge>
              ))}
            </div>
          </div>

          {/* Use Cases */}
          {template.use_cases.length > 0 && (
            <div>
              <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
                Use Cases
              </h4>
              <ul className="list-disc list-inside space-y-1 text-sm text-neutral-700 dark:text-neutral-300">
                {template.use_cases.map((useCase, index) => (
                  <li key={index}>{useCase}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Required Fields */}
          {template.required_fields.length > 0 && (
            <div>
              <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
                Required Dataset Fields
              </h4>
              <div className="flex gap-2 flex-wrap">
                {template.required_fields.map(field => (
                  <Badge key={field} variant="warning" size="sm">
                    {field}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Optional Fields */}
          {template.optional_fields.length > 0 && (
            <div>
              <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
                Optional Dataset Fields
              </h4>
              <div className="flex gap-2 flex-wrap">
                {template.optional_fields.map(field => (
                  <Badge key={field} variant="neutral" size="sm">
                    {field}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Sample Configuration */}
          {template.sample_config && (
            <div>
              <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
                Sample Configuration
              </h4>
              <div className="bg-neutral-50 dark:bg-neutral-800 rounded border p-4">
                <pre className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono overflow-x-auto">
                  {JSON.stringify(template.sample_config, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Tags */}
          {template.tags.length > 0 && (
            <div>
              <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Tags</h4>
              <div className="flex gap-2 flex-wrap">
                {template.tags.map(tag => (
                  <span key={tag} className="text-sm text-neutral-500 dark:text-neutral-400">
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between pt-6 border-t border-neutral-200 dark:border-neutral-700">
            <div className="text-sm text-neutral-500 dark:text-neutral-400">
              Created {template.created_at && new Date(template.created_at).toLocaleDateString()}
            </div>
            
            <div className="flex gap-3">
              <Button variant="neutral" onClick={() => setShowDetails(false)}>
                Close
              </Button>
              {onSelect && (
                <Button variant="primary" onClick={() => {
                  onSelect(template);
                  setShowDetails(false);
                }}>
                  Use This Template
                </Button>
              )}
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}