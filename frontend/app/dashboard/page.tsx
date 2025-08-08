'use client';

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
  TableEmpty
} from '@/components/ui/table';
import { Loading } from '@/components/ui/loading';
import { Container } from '@/components/layout/container';
import { useRuns, useWebSocket } from '@/hooks';
import { EvaluationRun, RunStatus, FilterOptions } from '@/types';

const Dashboard: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<RunStatus | 'all'>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  const {
    runs,
    loading,
    error,
    total,
    hasNext,
    hasPrev,
    filters,
    setFilters,
    refetch,
    clearError
  } = useRuns({
    limit: itemsPerPage,
    offset: (currentPage - 1) * itemsPerPage,
    search: searchTerm,
    status: statusFilter !== 'all' ? statusFilter : undefined,
  });

  // WebSocket for real-time updates
  const { lastMessage } = useWebSocket({ autoConnect: true });

  // Update runs when WebSocket receives updates (with throttling)
  React.useEffect(() => {
    if (lastMessage?.type === 'run_update' ||
        lastMessage?.type === 'progress' ||
        lastMessage?.type === 'completion' ||
        lastMessage?.type === 'error') {

      // Throttle WebSocket-triggered refetches
      const timeoutId = setTimeout(() => {
        refetch();
      }, 1000); // Only refetch once per second from WebSocket updates

      return () => clearTimeout(timeoutId);
    }
  }, [lastMessage?.type, lastMessage?.timestamp]); // More specific dependencies

  // Handle search with proper debouncing
  React.useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (searchTerm !== filters.search) {
        setFilters({ ...filters, search: searchTerm, offset: 0 });
        setCurrentPage(1);
      }
    }, 500); // Increased debounce delay

    return () => clearTimeout(timeoutId);
  }, [searchTerm, filters.search]); // Only depend on searchTerm and current search filter

  // Handle status filter change
  const handleStatusFilterChange = React.useCallback((status: RunStatus | 'all') => {
    if (status !== statusFilter) {
      setStatusFilter(status);
      setFilters({
        ...filters,
        status: status !== 'all' ? status : undefined,
        offset: 0
      });
      setCurrentPage(1);
    }
  }, [statusFilter, setFilters]);

  // Handle sorting
  const handleSort = React.useCallback((sortBy: 'created_at' | 'updated_at' | 'name' | 'status' | 'duration_seconds') => {
    const newOrder = filters.sortBy === sortBy && filters.sortOrder === 'asc' ? 'desc' : 'asc';
    setFilters({ ...filters, sortBy, sortOrder: newOrder });
  }, [filters, setFilters]);

  // Handle pagination
  const handlePageChange = React.useCallback((direction: 'next' | 'prev') => {
    const newPage = direction === 'next' ? currentPage + 1 : currentPage - 1;
    setCurrentPage(newPage);
    setFilters({
      ...filters,
      offset: (newPage - 1) * itemsPerPage
    });
  }, [currentPage, itemsPerPage, filters, setFilters]);

  // Calculate stats from runs
  const stats = useMemo(() => {
    const totalRuns = total;
    const successfulRuns = runs.filter(run => run.status === 'completed').length;
    const failedRuns = runs.filter(run => run.status === 'failed').length;
    const runningRuns = runs.filter(run => run.status === 'running').length;

    return {
      totalRuns,
      successfulRuns,
      failedRuns,
      runningRuns,
      successRate: totalRuns > 0 ? ((successfulRuns / totalRuns) * 100).toFixed(1) : '0',
    };
  }, [runs, total]);

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const getStatusBadge = (status: RunStatus) => {
    switch (status) {
      case 'completed':
        return <Badge variant="success" size="sm">Completed</Badge>;
      case 'failed':
        return <Badge variant="danger" size="sm">Failed</Badge>;
      case 'running':
        return <Badge variant="warning" size="sm">Running</Badge>;
      case 'pending':
        return <Badge variant="secondary" size="sm">Pending</Badge>;
      case 'cancelled':
        return <Badge variant="secondary" size="sm">Cancelled</Badge>;
      default:
        return <Badge variant="secondary" size="sm">Unknown</Badge>;
    }
  };

  const getProgressPercentage = (run: EvaluationRun) => {
    if (run.total_items === 0) return 0;
    return Math.round((run.processed_items / run.total_items) * 100);
  };

  if (error) {
    return (
      <div className="flex-1 overflow-auto">
        <Container className="py-8">
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-destructive-600 dark:text-destructive-400">
                Error Loading Dashboard
              </h2>
              <Button variant="outline" size="sm" onClick={clearError}>
                Dismiss
              </Button>
            </div>
            <p className="text-neutral-600 dark:text-neutral-300 mb-4">{error}</p>
            <Button onClick={refetch} variant="default" size="sm">
              Retry
            </Button>
          </Card>
        </Container>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <Container className="py-8 space-y-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
              Run Browser
            </h1>
            <p className="text-neutral-600 dark:text-neutral-300 mt-1">
              Manage and analyze your LLM evaluation runs
            </p>
          </div>

          <div className="flex gap-3">
            <Link href="/runs/new">
              <Button variant="default" size="md">
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                </svg>
                New Evaluation
              </Button>
            </Link>
            <Link href="/compare">
              <Button variant="secondary" size="md">
                Compare Runs
              </Button>
            </Link>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-neutral-600 dark:text-neutral-300">
                  Total Runs
                </p>
                <p className="text-3xl font-bold text-neutral-900 dark:text-white mt-2">
                  {loading ? '...' : stats.totalRuns}
                </p>
              </div>
              <div className="w-12 h-12 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center">
                <svg className="w-6 h-6 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
              </div>
            </div>
          </Card>

          <Card className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-neutral-600 dark:text-neutral-300">
                  Success Rate
                </p>
                <p className="text-3xl font-bold text-neutral-900 dark:text-white mt-2">
                  {loading ? '...' : `${stats.successRate}%`}
                </p>
              </div>
              <div className="w-12 h-12 bg-success-100 dark:bg-success-900/30 rounded-lg flex items-center justify-center">
                <svg className="w-6 h-6 text-success-600 dark:text-success-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
            </div>
          </Card>

          <Card className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-neutral-600 dark:text-neutral-300">
                  Running
                </p>
                <p className="text-3xl font-bold text-neutral-900 dark:text-white mt-2">
                  {loading ? '...' : stats.runningRuns}
                </p>
              </div>
              <div className="w-12 h-12 bg-warning-100 dark:bg-warning-900/30 rounded-lg flex items-center justify-center">
                <svg className="w-6 h-6 text-warning-600 dark:text-warning-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
            </div>
          </Card>

          <Card className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-neutral-600 dark:text-neutral-300">
                  Failed
                </p>
                <p className="text-3xl font-bold text-neutral-900 dark:text-white mt-2">
                  {loading ? '...' : stats.failedRuns}
                </p>
              </div>
              <div className="w-12 h-12 bg-destructive-100 dark:bg-destructive-900/30 rounded-lg flex items-center justify-center">
                <svg className="w-6 h-6 text-destructive-600 dark:text-destructive-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
            </div>
          </Card>
        </div>

        {/* Search and Filters */}
        <Card className="p-6">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <Input
                placeholder="Search runs by name, template, or dataset..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                }
              />
            </div>
            <div className="sm:w-48">
              <Select
                value={statusFilter}
                onChange={(e) => handleStatusFilterChange(e.target.value as RunStatus | 'all')}
                options={[
                  { value: 'all', label: 'All Statuses' },
                  { value: 'completed', label: 'Completed' },
                  { value: 'running', label: 'Running' },
                  { value: 'failed', label: 'Failed' },
                  { value: 'pending', label: 'Pending' },
                  { value: 'cancelled', label: 'Cancelled' },
                ]}
              />
            </div>
          </div>
        </Card>

        {/* Runs Table */}
        <Card>
          {loading ? (
            <div className="p-12 text-center">
              <Loading size="lg" />
              <p className="text-neutral-600 dark:text-neutral-300 mt-4">Loading evaluation runs...</p>
            </div>
          ) : runs.length === 0 ? (
            <div className="p-12 text-center">
              <svg className="w-12 h-12 text-neutral-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">No runs found</h3>
              <p className="text-neutral-600 dark:text-neutral-300 mb-4">
                {searchTerm || statusFilter !== 'all'
                  ? 'Try adjusting your search or filters.'
                  : 'Get started by creating your first evaluation run.'}
              </p>
              <Link href="/runs/new">
                <Button variant="default" size="md">
                  Create First Run
                </Button>
              </Link>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead
                    sortable
                    sorted={filters.sortBy === 'name' ? filters.sortOrder as 'asc' | 'desc' : false}
                    onClick={() => handleSort('name')}
                  >
                    Run Name
                  </TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead
                    sortable
                    sorted={filters.sortBy === 'created_at' ? filters.sortOrder as 'asc' | 'desc' : false}
                    onClick={() => handleSort('created_at')}
                  >
                    Created
                  </TableHead>
                  <TableHead
                    sortable
                    sorted={filters.sortBy === 'duration_seconds' ? filters.sortOrder as 'asc' | 'desc' : false}
                    onClick={() => handleSort('duration_seconds')}
                  >
                    Duration
                  </TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.length === 0 ? (
                  <TableEmpty
                    colSpan={7}
                    message={searchTerm || statusFilter !== 'all'
                      ? 'No runs match your filters.'
                      : 'No evaluation runs found.'}
                  />
                ) : (
                  runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>
                        <div>
                          <Link
                            href={`/dashboard/runs/${run.id}`}
                            className="text-primary-600 dark:text-primary-400 hover:underline font-medium"
                          >
                            {run.name}
                          </Link>
                          {run.description && (
                            <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                              {run.description}
                            </p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        {getStatusBadge(run.status)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 min-w-32">
                          <div className="flex-1 bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                            <div
                              className={`h-2 rounded-full transition-all ${
                                run.status === 'completed' ? 'bg-success-500' :
                                run.status === 'failed' ? 'bg-destructive-500' :
                                run.status === 'running' ? 'bg-warning-500' : 'bg-neutral-400'
                              }`}
                              style={{ width: `${getProgressPercentage(run)}%` }}
                            />
                          </div>
                          <span className="text-sm text-neutral-600 dark:text-neutral-300 whitespace-nowrap">
                            {run.processed_items}/{run.total_items}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {run.template_name || 'Custom'}
                      </TableCell>
                      <TableCell>
                        {formatTimestamp(run.created_at)}
                      </TableCell>
                      <TableCell>
                        {formatDuration(run.duration_seconds)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Link href={`/dashboard/runs/${run.id}`}>
                            <Button variant="ghost" size="sm">
                              View
                            </Button>
                          </Link>
                          {run.langfuse_session_id && (
                            <a
                              href={`https://cloud.langfuse.com/project/sessions/${run.langfuse_session_id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <Button variant="ghost" size="sm">
                                Langfuse
                              </Button>
                            </a>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}

          {/* Pagination */}
          {(hasNext || hasPrev) && (
            <div className="p-6 border-t border-neutral-200 dark:border-neutral-700">
              <div className="flex items-center justify-between">
                <div className="text-sm text-neutral-600 dark:text-neutral-300">
                  Showing {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, total)} of {total} results
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasPrev}
                    onClick={() => handlePageChange('prev')}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasNext}
                    onClick={() => handlePageChange('next')}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </div>
          )}
        </Card>
      </Container>
    </div>
  );
};

export default Dashboard;
