'use client';

import React, { useState, useEffect } from 'react';
import { Badge } from './badge';
import { Button } from './button';
import { Select } from './select';
import { Loading } from './loading';
import { RunItem, PaginatedResponse } from '../../types';

interface RunItemsTableProps {
  items: PaginatedResponse<RunItem> | null;
  loading: boolean;
  onFetchItems: (limit?: number, offset?: number, status?: 'success' | 'failed' | 'pending') => Promise<void>;
}

export const RunItemsTable: React.FC<RunItemsTableProps> = ({
  items,
  loading,
  onFetchItems,
}) => {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState<'success' | 'failed' | 'pending' | 'all'>('all');
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Fetch items on mount and when filters change
  useEffect(() => {
    const offset = (currentPage - 1) * pageSize;
    const status = statusFilter === 'all' ? undefined : statusFilter;
    onFetchItems(pageSize, offset, status);
  }, [currentPage, pageSize, statusFilter, onFetchItems]);

  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage);
  };

  const handlePageSizeChange = (newPageSize: number) => {
    setPageSize(newPageSize);
    setCurrentPage(1); // Reset to first page
  };

  const handleStatusFilterChange = (newStatus: 'success' | 'failed' | 'pending' | 'all') => {
    setStatusFilter(newStatus);
    setCurrentPage(1); // Reset to first page
  };

  const toggleRowExpansion = (itemId: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(itemId)) {
      newExpanded.delete(itemId);
    } else {
      newExpanded.add(itemId);
    }
    setExpandedRows(newExpanded);
  };

  const getStatusBadge = (status: 'success' | 'failed' | 'pending') => {
    switch (status) {
      case 'success':
        return <Badge variant="success" size="sm">Success</Badge>;
      case 'failed':
        return <Badge variant="danger" size="sm">Failed</Badge>;
      case 'pending':
        return <Badge variant="warning" size="sm">Pending</Badge>;
      default:
        return <Badge variant="secondary" size="sm">Unknown</Badge>;
    }
  };

  const formatScore = (score: number) => {
    return (score * 100).toFixed(1) + '%';
  };

  const formatDuration = (responseTime?: number) => {
    if (!responseTime) return 'N/A';
    if (responseTime < 1) return `${(responseTime * 1000).toFixed(0)}ms`;
    return `${responseTime.toFixed(2)}s`;
  };

  const truncateText = (text: string, maxLength: number = 100) => {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength) + '...';
  };

  if (loading && !items) {
    return (
      <div className="flex justify-center items-center py-8">
        <Loading size="md" />
        <span className="ml-3 text-neutral-600 dark:text-neutral-300">Loading items...</span>
      </div>
    );
  }

  if (!items || items.items.length === 0) {
    return (
      <div className="text-center py-8">
        <div className="text-neutral-500 dark:text-neutral-400 mb-4">
          {statusFilter !== 'all'
            ? `No ${statusFilter} items found for this run.`
            : 'No items found for this run.'
          }
        </div>
        <Button variant="outline" onClick={() => onFetchItems()}>
          Refresh
        </Button>
      </div>
    );
  }

  const totalPages = Math.ceil(items.total / pageSize);

  return (
    <div className="space-y-4">
      {/* Filters and Controls */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-600 dark:text-neutral-300">Status:</span>
            <Select
              value={statusFilter}
              onChange={(e) => handleStatusFilterChange(e.target.value as 'success' | 'failed' | 'pending' | 'all')}
              options={[
                { value: 'all', label: 'All' },
                { value: 'success', label: 'Success' },
                { value: 'failed', label: 'Failed' },
                { value: 'pending', label: 'Pending' },
              ]}
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-600 dark:text-neutral-300">Per page:</span>
            <Select
              value={pageSize.toString()}
              onChange={(e) => handlePageSizeChange(parseInt(e.target.value))}
              options={[
                { value: '10', label: '10' },
                { value: '20', label: '20' },
                { value: '50', label: '50' },
                { value: '100', label: '100' },
              ]}
            />
          </div>
        </div>
        <div className="text-sm text-neutral-600 dark:text-neutral-300">
          Showing {((currentPage - 1) * pageSize) + 1} to {Math.min(currentPage * pageSize, items.total)} of {items.total} items
        </div>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-neutral-50 dark:bg-neutral-900/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  Item
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  Scores
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  Performance
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
              {items.items.map((item, index) => {
                const isExpanded = expandedRows.has(item.id);
                return (
                  <React.Fragment key={item.id}>
                    <tr className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50">
                      <td className="px-4 py-3">
                        <div className="flex items-start space-y-1">
                          <div className="text-sm font-medium text-neutral-900 dark:text-white">
                            Item {((currentPage - 1) * pageSize) + index + 1}
                          </div>
                        </div>
                        {item.input_data && Object.keys(item.input_data).length > 0 && (
                          <div className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                            {Object.entries(item.input_data).slice(0, 2).map(([key, value]) => (
                              <div key={key}>
                                <span className="font-medium">{key}:</span> {truncateText(String(value), 60)}
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {getStatusBadge(item.status)}
                        {item.error_message && (
                          <div className="text-xs text-destructive-600 dark:text-destructive-400 mt-1">
                            {truncateText(item.error_message, 60)}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-1">
                          {Object.entries(item.scores).map(([metric, score]) => (
                            <div key={metric} className="flex justify-between items-center text-xs">
                              <span className="text-neutral-600 dark:text-neutral-300 capitalize">
                                {metric.replace(/_/g, ' ')}:
                              </span>
                              <span className={`font-medium ${
                                score >= 0.8 ? 'text-success-600 dark:text-success-400' :
                                score >= 0.6 ? 'text-warning-600 dark:text-warning-400' :
                                'text-destructive-600 dark:text-destructive-400'
                              }`}>
                                {formatScore(score)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-1 text-xs text-neutral-600 dark:text-neutral-300">
                          {item.response_time && (
                            <div>Response: {formatDuration(item.response_time)}</div>
                          )}
                          {item.tokens_used && (
                            <div>Tokens: {item.tokens_used.toLocaleString()}</div>
                          )}
                          {item.cost && (
                            <div>Cost: ${item.cost.toFixed(4)}</div>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleRowExpansion(item.id)}
                        >
                          {isExpanded ? 'Hide' : 'Details'}
                        </Button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td colSpan={5} className="px-4 py-3 bg-neutral-50 dark:bg-neutral-900/20">
                          <div className="space-y-4">
                            {/* Input Data */}
                            <div>
                              <h4 className="text-sm font-medium text-neutral-900 dark:text-white mb-2">Input Data</h4>
                              <pre className="text-xs bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded p-3 overflow-auto max-h-40">
                                {JSON.stringify(item.input_data, null, 2)}
                              </pre>
                            </div>

                            {/* Output Data */}
                            {item.output_data && (
                              <div>
                                <h4 className="text-sm font-medium text-neutral-900 dark:text-white mb-2">Output Data</h4>
                                <pre className="text-xs bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded p-3 overflow-auto max-h-40">
                                  {JSON.stringify(item.output_data, null, 2)}
                                </pre>
                              </div>
                            )}

                            {/* Expected Output */}
                            {item.expected_output && (
                              <div>
                                <h4 className="text-sm font-medium text-neutral-900 dark:text-white mb-2">Expected Output</h4>
                                <pre className="text-xs bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded p-3 overflow-auto max-h-40">
                                  {JSON.stringify(item.expected_output, null, 2)}
                                </pre>
                              </div>
                            )}

                            {/* Full Error Message */}
                            {item.error_message && (
                              <div>
                                <h4 className="text-sm font-medium text-destructive-700 dark:text-destructive-300 mb-2">Error Details</h4>
                                <pre className="text-xs text-destructive-600 dark:text-destructive-400 bg-destructive-50 dark:bg-destructive-900/20 border border-destructive-200 dark:border-destructive-800 rounded p-3 overflow-auto max-h-40">
                                  {item.error_message}
                                </pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-4 py-3 border-t border-neutral-200 dark:border-neutral-700 flex items-center justify-between">
            <div className="text-sm text-neutral-600 dark:text-neutral-300">
              Page {currentPage} of {totalPages}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage <= 1}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage >= totalPages}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
