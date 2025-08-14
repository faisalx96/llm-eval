'use client';

import React, { useState, useMemo } from 'react';
import { Card } from './card';
import { Input } from './input';
import { Button } from './button';
import { Badge } from './badge';
import { Loading } from './loading';
import { DatasetPreviewModal } from './dataset-preview-modal';
import { useDatasets } from '@/hooks/useDatasets';
import { Dataset } from '@/types';
import { cn } from '@/lib/utils';

interface DatasetBrowserProps {
  onSelectDataset?: (dataset: Dataset) => void;
  selectedDatasetId?: string;
  selectionMode?: boolean;
  className?: string;
}

export function DatasetBrowser({ 
  onSelectDataset, 
  selectedDatasetId, 
  selectionMode = false,
  className 
}: DatasetBrowserProps) {
  const [search, setSearch] = useState('');
  const [currentPage, setCurrentPage] = useState(0);
  const [previewDataset, setPreviewDataset] = useState<Dataset | null>(null);
  
  const pageSize = 12;
  
  const { datasets, loading, error, pagination, refetch } = useDatasets({
    search: search.trim() || undefined,
    limit: pageSize,
    offset: currentPage * pageSize
  });

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setCurrentPage(0); // Reset to first page when searching
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const handleDatasetSelect = (dataset: Dataset) => {
    if (onSelectDataset) {
      onSelectDataset(dataset);
    }
  };

  const handlePreviewDataset = (dataset: Dataset) => {
    setPreviewDataset(dataset);
  };

  const formatLastUsed = (date?: string) => {
    if (!date) return 'Never used';
    
    const lastUsed = new Date(date);
    const now = new Date();
    const diffInHours = (now.getTime() - lastUsed.getTime()) / (1000 * 60 * 60);
    
    if (diffInHours < 24) {
      return `${Math.floor(diffInHours)}h ago`;
    } else if (diffInHours < 24 * 7) {
      return `${Math.floor(diffInHours / 24)}d ago`;
    } else {
      return lastUsed.toLocaleDateString();
    }
  };

  const totalPages = Math.ceil(pagination.total / pageSize);

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
            Dataset Browser
          </h2>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            Browse and explore your Langfuse datasets
          </p>
        </div>
        
        <Button variant="neutral" onClick={refetch} disabled={loading}>
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </Button>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <Input
            type="text"
            placeholder="Search datasets by name or description..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="w-full"
            leftIcon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            }
          />
        </div>
        
        {pagination.total > 0 && (
          <div className="text-sm text-neutral-500 dark:text-neutral-400 whitespace-nowrap">
            {pagination.total} dataset{pagination.total !== 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Loading State */}
      {loading && datasets.length === 0 && (
        <div className="text-center py-12">
          <Loading size="lg" />
          <p className="mt-4 text-neutral-600 dark:text-neutral-400">Loading datasets...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 text-center">
          <p className="text-red-600 dark:text-red-400 mb-4">
            Failed to load datasets: {error.message}
          </p>
          <Button variant="primary" onClick={refetch}>
            Try Again
          </Button>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && datasets.length === 0 && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 bg-neutral-100 dark:bg-neutral-800 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5a2 2 0 012-2h4a2 2 0 012 2v2H8V5z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
            {search ? 'No datasets found' : 'No datasets available'}
          </h3>
          <p className="text-neutral-500 dark:text-neutral-400 mb-4">
            {search 
              ? `No datasets match "${search}". Try adjusting your search terms.`
              : 'Create datasets in Langfuse to see them here.'
            }
          </p>
          {search && (
            <Button variant="neutral" onClick={() => setSearch('')}>
              Clear Search
            </Button>
          )}
        </div>
      )}

      {/* Dataset Grid */}
      {!loading && datasets.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {datasets.map((dataset) => (
            <Card
              key={dataset.id}
              className={cn(
                'p-6 cursor-pointer transition-all duration-200',
                'hover:shadow-md hover:border-primary-200 dark:hover:border-primary-800',
                selectionMode && selectedDatasetId === dataset.id && 
                'ring-2 ring-primary-500 border-primary-500 bg-primary-50 dark:bg-primary-900/20'
              )}
              onClick={() => handleDatasetSelect(dataset)}
            >
              <div className="space-y-4">
                {/* Header */}
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-neutral-900 dark:text-white truncate">
                      {dataset.name}
                    </h3>
                    {dataset.description && (
                      <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1 line-clamp-2">
                        {dataset.description}
                      </p>
                    )}
                  </div>
                  
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePreviewDataset(dataset);
                    }}
                    className="ml-2 p-1 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 rounded transition-colors"
                    title="Preview dataset"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  </button>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">Items</p>
                    <p className="text-lg font-medium text-neutral-900 dark:text-white">
                      {dataset.item_count.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">Last Used</p>
                    <p className="text-sm text-neutral-700 dark:text-neutral-300">
                      {formatLastUsed(dataset.last_used)}
                    </p>
                  </div>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between pt-4 border-t border-neutral-100 dark:border-neutral-700">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400">
                    Created {new Date(dataset.created_at).toLocaleDateString()}
                  </div>
                  
                  {selectionMode && selectedDatasetId === dataset.id && (
                    <Badge variant="primary" size="sm">
                      Selected
                    </Badge>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            Showing {currentPage * pageSize + 1} to {Math.min((currentPage + 1) * pageSize, pagination.total)} of {pagination.total} results
          </div>
          
          <div className="flex items-center gap-2">
            <Button
              variant="neutral"
              size="sm"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={!pagination.hasPrev}
            >
              Previous
            </Button>
            
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const pageIndex = Math.max(0, Math.min(currentPage - 2, totalPages - 5)) + i;
                return (
                  <Button
                    key={pageIndex}
                    variant={pageIndex === currentPage ? 'primary' : 'neutral'}
                    size="sm"
                    onClick={() => handlePageChange(pageIndex)}
                    className="w-8 h-8 p-0"
                  >
                    {pageIndex + 1}
                  </Button>
                );
              })}
            </div>
            
            <Button
              variant="neutral"
              size="sm"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={!pagination.hasNext}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Preview Modal */}
      <DatasetPreviewModal
        dataset={previewDataset}
        isOpen={previewDataset !== null}
        onClose={() => setPreviewDataset(null)}
      />
    </div>
  );
}