'use client';

import React, { useState, useMemo } from 'react';
import { Card } from './card';
import { Table } from './table';
import { Badge } from './badge';
import { Input } from './input';
import { Button } from './button';
import { RunComparison } from '../../types';

interface ItemLevelComparisonProps {
  comparison: RunComparison;
  className?: string;
}

export const ItemLevelComparison: React.FC<ItemLevelComparisonProps> = ({
  comparison,
  className = '',
}) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'improved' | 'regressed' | 'failed'>('all');
  const [sortBy, setSortBy] = useState<string>('index');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(20);

  const metricNames = useMemo(() => {
    return Object.keys(comparison.comparison.metrics);
  }, [comparison]);

  const filteredItems = useMemo(() => {
    let items = comparison.item_level_comparison.map((item, index) => ({
      ...item,
      index: index + 1,
    }));

    // Apply search filter
    if (search) {
      items = items.filter(item => 
        JSON.stringify(item.input_data).toLowerCase().includes(search.toLowerCase()) ||
        item.item_id.toLowerCase().includes(search.toLowerCase())
      );
    }

    // Apply status filter
    if (statusFilter !== 'all') {
      items = items.filter(item => {
        const hasImprovements = Object.values(item.differences).some(diff => diff > 0);
        const hasRegressions = Object.values(item.differences).some(diff => diff < 0);
        const hasFailed = item.run1_status === 'failed' || item.run2_status === 'failed';

        switch (statusFilter) {
          case 'improved':
            return hasImprovements && !hasRegressions && !hasFailed;
          case 'regressed':
            return hasRegressions && !hasFailed;
          case 'failed':
            return hasFailed;
          default:
            return true;
        }
      });
    }

    // Apply sorting
    items.sort((a, b) => {
      let aValue, bValue;

      if (sortBy === 'index') {
        aValue = a.index;
        bValue = b.index;
      } else if (metricNames.includes(sortBy)) {
        aValue = a.differences[sortBy] || 0;
        bValue = b.differences[sortBy] || 0;
      } else {
        aValue = a.item_id;
        bValue = b.item_id;
      }

      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortOrder === 'asc' 
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue);
      }

      if (typeof aValue === 'number' && typeof bValue === 'number') {
        return sortOrder === 'asc' ? aValue - bValue : bValue - aValue;
      }

      // Fallback for mixed types
      return 0;
    });

    return items;
  }, [comparison.item_level_comparison, search, statusFilter, sortBy, sortOrder, metricNames]);

  const paginatedItems = useMemo(() => {
    const startIndex = (currentPage - 1) * itemsPerPage;
    return filteredItems.slice(startIndex, startIndex + itemsPerPage);
  }, [filteredItems, currentPage, itemsPerPage]);

  const totalPages = Math.ceil(filteredItems.length / itemsPerPage);

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

  const getDiffColor = (diff: number) => {
    if (diff > 0) return 'text-success-600 dark:text-success-400';
    if (diff < 0) return 'text-danger-600 dark:text-danger-400';
    return 'text-neutral-600 dark:text-neutral-400';
  };

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case 'success': return 'success';
      case 'failed': return 'danger';
      default: return 'secondary';
    }
  };

  const renderInputData = (inputData: Record<string, any>) => {
    const entries = Object.entries(inputData);
    if (entries.length === 0) return '-';

    // Show first few key-value pairs, truncated
    const display = entries.slice(0, 2).map(([key, value]) => {
      const valueStr = typeof value === 'string' ? value : JSON.stringify(value);
      const truncated = valueStr.length > 50 ? valueStr.substring(0, 50) + '...' : valueStr;
      return `${key}: ${truncated}`;
    }).join(', ');

    return entries.length > 2 ? `${display}, ...` : display;
  };

  return (
    <Card className={`${className}`}>
      <div className="p-6 border-b border-neutral-200 dark:border-neutral-700">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-neutral-900 dark:text-white">
            Item-Level Comparison
          </h3>
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            {filteredItems.length} of {comparison.item_level_comparison.length} items
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Input
              type="text"
              placeholder="Search items..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full"
            />
          </div>
          
          <div className="flex gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
              className="flex h-10 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-600 dark:bg-neutral-800 dark:ring-offset-neutral-800 min-w-[120px]"
            >
              <option value="all">All Items</option>
              <option value="improved">Improved</option>
              <option value="regressed">Regressed</option>
              <option value="failed">Failed</option>
            </select>
            
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="flex h-10 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-600 dark:bg-neutral-800 dark:ring-offset-neutral-800 min-w-[120px]"
            >
              <option value="index">Index</option>
              {metricNames.map(metric => (
                <option key={metric} value={metric}>
                  {metric} diff
                </option>
              ))}
            </select>
            
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              className="px-3"
            >
              {sortOrder === 'asc' ? '↑' : '↓'}
            </Button>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto mobile-scroll-table">
        <Table className="min-w-[800px]">
          <thead>
            <tr>
              <th className="text-left">#</th>
              <th className="text-left">Input Data</th>
              <th className="text-left">Status</th>
              {metricNames.map(metric => (
                <th key={metric} className="text-center">{metric}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedItems.map((item) => (
              <tr key={item.item_id}>
                <td className="font-mono text-sm">
                  {item.index}
                </td>
                <td className="max-w-md">
                  <div className="text-sm text-neutral-600 dark:text-neutral-300">
                    {renderInputData(item.input_data)}
                  </div>
                </td>
                <td>
                  <div className="flex gap-1">
                    <Badge variant={getStatusBadgeVariant(item.run1_status)} size="sm">
                      R1: {item.run1_status}
                    </Badge>
                    <Badge variant={getStatusBadgeVariant(item.run2_status)} size="sm">
                      R2: {item.run2_status}
                    </Badge>
                  </div>
                </td>
                {metricNames.map(metric => {
                  const run1Score = item.run1_scores[metric] || 0;
                  const run2Score = item.run2_scores[metric] || 0;
                  const difference = item.differences[metric] || 0;
                  
                  return (
                    <td key={metric} className="text-center font-mono text-sm">
                      <div className="space-y-1">
                        <div className="text-neutral-600 dark:text-neutral-400">
                          {formatScore(run1Score)} → {formatScore(run2Score)}
                        </div>
                        <div className={getDiffColor(difference)}>
                          {formatDifference(difference)}
                        </div>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-700">
          <div className="flex items-center justify-between">
            <div className="text-sm text-neutral-500 dark:text-neutral-400">
              Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(currentPage * itemsPerPage, filteredItems.length)} of {filteredItems.length} items
            </div>
            
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(page => Math.max(1, page - 1))}
                disabled={currentPage === 1}
                className="mobile-touch-target"
              >
                Previous
              </Button>
              
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const pageNum = currentPage <= 3 ? i + 1 : currentPage - 2 + i;
                  if (pageNum > totalPages) return null;
                  
                  return (
                    <Button
                      key={pageNum}
                      variant={pageNum === currentPage ? "default" : "outline"}
                      size="sm"
                      onClick={() => setCurrentPage(pageNum)}
                      className="w-8 h-8 p-0 mobile-touch-target"
                    >
                      {pageNum}
                    </Button>
                  );
                })}
              </div>
              
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(page => Math.min(totalPages, page + 1))}
                disabled={currentPage === totalPages}
                className="mobile-touch-target"
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
};