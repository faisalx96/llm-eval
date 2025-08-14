'use client';

import React from 'react';
import { Modal } from './modal';
import { Button } from './button';
import { Loading } from './loading';
import { Badge } from './badge';
import { Card } from './card';
import { useDatasetItems } from '@/hooks/useDatasets';
import { Dataset, DatasetItem } from '@/types';
import { cn } from '@/lib/utils';

interface DatasetPreviewModalProps {
  dataset: Dataset | null;
  isOpen: boolean;
  onClose: () => void;
}

export function DatasetPreviewModal({ dataset, isOpen, onClose }: DatasetPreviewModalProps) {
  const { items, loading, error } = useDatasetItems(dataset?.id || null, { limit: 10 });

  const formatValue = (value: any, maxLength = 100): string => {
    if (value === null || value === undefined) return 'null';
    
    const str = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    
    if (str.length > maxLength) {
      return str.substring(0, maxLength) + '...';
    }
    
    return str;
  };

  const getFieldType = (value: any): string => {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'object') {
      if (Array.isArray(value)) return 'array';
      return 'object';
    }
    return typeof value;
  };

  if (!dataset) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Dataset Preview: ${dataset.name}`}
      size="xl"
    >
      <div className="space-y-6">
        {/* Dataset Info */}
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-3">
              Dataset Information
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-neutral-500 dark:text-neutral-400">Total Items</p>
                <p className="text-lg font-medium text-neutral-900 dark:text-white">
                  {dataset.item_count.toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-sm text-neutral-500 dark:text-neutral-400">Created</p>
                <p className="text-sm text-neutral-900 dark:text-white">
                  {new Date(dataset.created_at).toLocaleDateString()}
                </p>
              </div>
            </div>
            {dataset.description && (
              <div className="mt-4">
                <p className="text-sm text-neutral-500 dark:text-neutral-400">Description</p>
                <p className="text-sm text-neutral-900 dark:text-white mt-1">
                  {dataset.description}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Data Preview */}
        <div>
          <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-3">
            Sample Data (First 10 items)
          </h3>
          
          {loading && (
            <div className="flex items-center justify-center py-8">
              <Loading size="md" text="Loading dataset items..." />
            </div>
          )}

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
              <p className="text-sm text-red-600 dark:text-red-400">
                Failed to load dataset items: {error.message}
              </p>
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className="bg-neutral-50 dark:bg-neutral-800 rounded-lg p-8 text-center">
              <p className="text-neutral-500 dark:text-neutral-400">
                No items found in this dataset
              </p>
            </div>
          )}

          {!loading && !error && items.length > 0 && (
            <div className="space-y-4 max-h-96 overflow-y-auto">
              {items.map((item, index) => (
                <Card key={item.id} className="p-4">
                  <div className="flex items-start justify-between mb-3">
                    <h4 className="font-medium text-neutral-900 dark:text-white">
                      Item {index + 1}
                    </h4>
                    <Badge variant="neutral" size="sm">
                      {item.id.substring(0, 8)}
                    </Badge>
                  </div>
                  
                  <div className="space-y-3">
                    {/* Input */}
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                          Input
                        </span>
                        <Badge variant="neutral" size="sm">
                          {getFieldType(item.input)}
                        </Badge>
                      </div>
                      <div className="bg-neutral-50 dark:bg-neutral-800 rounded border p-3">
                        <pre className="text-xs text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono">
                          {formatValue(item.input, 300)}
                        </pre>
                      </div>
                    </div>

                    {/* Expected Output */}
                    {item.expected_output && (
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                            Expected Output
                          </span>
                          <Badge variant="neutral" size="sm">
                            {getFieldType(item.expected_output)}
                          </Badge>
                        </div>
                        <div className="bg-neutral-50 dark:bg-neutral-800 rounded border p-3">
                          <pre className="text-xs text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono">
                            {formatValue(item.expected_output, 300)}
                          </pre>
                        </div>
                      </div>
                    )}

                    {/* Metadata */}
                    {item.metadata && Object.keys(item.metadata).length > 0 && (
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                            Metadata
                          </span>
                          <Badge variant="neutral" size="sm">
                            object
                          </Badge>
                        </div>
                        <div className="bg-neutral-50 dark:bg-neutral-800 rounded border p-3">
                          <pre className="text-xs text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono">
                            {formatValue(item.metadata, 200)}
                          </pre>
                        </div>
                      </div>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <Button variant="neutral" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}