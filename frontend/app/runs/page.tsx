'use client';

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
// import { Table } from '@/components/ui/table';
import { Container } from '@/components/layout/container';
import { cn } from '@/lib/utils';

interface EvaluationRun {
  id: string;
  name: string;
  status: 'completed' | 'failed' | 'running' | 'pending';
  score: number | null;
  timestamp: string;
  duration: string;
  dataset: string;
  model: string;
  metrics: string[];
  itemsProcessed: number;
  totalItems: number;
}

// Mock data - in real app this would come from API
const mockRuns: EvaluationRun[] = [
  {
    id: 'run-001',
    name: 'GPT-4 Summarization Test',
    status: 'completed',
    score: 0.92,
    timestamp: '2024-08-02T10:30:00Z',
    duration: '2m 34s',
    dataset: 'news-summaries-v1',
    model: 'gpt-4-turbo',
    metrics: ['Relevance', 'Coherence', 'Faithfulness'],
    itemsProcessed: 150,
    totalItems: 150,
  },
  {
    id: 'run-002',
    name: 'Claude-3 QA Evaluation',
    status: 'completed',
    score: 0.88,
    timestamp: '2024-08-02T09:15:00Z',
    duration: '1m 47s',
    dataset: 'qa-benchmark-v2',
    model: 'claude-3-sonnet',
    metrics: ['Correctness', 'Completeness'],
    itemsProcessed: 200,
    totalItems: 200,
  },
  {
    id: 'run-003',
    name: 'RAG Pipeline Test',
    status: 'failed',
    score: null,
    timestamp: '2024-08-02T08:45:00Z',
    duration: '45s',
    dataset: 'rag-eval-dataset',
    model: 'gpt-3.5-turbo',
    metrics: ['Answer Relevancy', 'Context Precision'],
    itemsProcessed: 25,
    totalItems: 100,
  },
  {
    id: 'run-004',
    name: 'Gemini Pro Comparison',
    status: 'running',
    score: null,
    timestamp: '2024-08-02T11:00:00Z',
    duration: '1m 12s',
    dataset: 'multi-turn-dialogue',
    model: 'gemini-pro',
    metrics: ['Helpfulness', 'Harmlessness'],
    itemsProcessed: 75,
    totalItems: 120,
  },
  {
    id: 'run-005',
    name: 'Code Generation Eval',
    status: 'pending',
    score: null,
    timestamp: '2024-08-02T11:15:00Z',
    duration: '-',
    dataset: 'code-problems-v3',
    model: 'gpt-4-code',
    metrics: ['Correctness', 'Efficiency', 'Style'],
    itemsProcessed: 0,
    totalItems: 80,
  },
  {
    id: 'run-006',
    name: 'Translation Quality Check',
    status: 'completed',
    score: 0.85,
    timestamp: '2024-08-02T07:30:00Z',
    duration: '3m 12s',
    dataset: 'multilingual-translate',
    model: 'claude-3-haiku',
    metrics: ['Fluency', 'Adequacy'],
    itemsProcessed: 300,
    totalItems: 300,
  },
];

const Runs: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [modelFilter, setModelFilter] = useState('all');
  const [sortField, setSortField] = useState<keyof EvaluationRun>('timestamp');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  // Filter and sort runs
  const filteredAndSortedRuns = useMemo(() => {
    const filtered = mockRuns.filter((run) => {
      const matchesSearch = run.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           run.dataset.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           run.model.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesStatus = statusFilter === 'all' || run.status === statusFilter;
      const matchesModel = modelFilter === 'all' || run.model === modelFilter;

      return matchesSearch && matchesStatus && matchesModel;
    });

    // Sort
    filtered.sort((a, b) => {
      let aValue = a[sortField];
      let bValue = b[sortField];

      if (sortField === 'timestamp') {
        aValue = new Date(aValue as string).getTime();
        bValue = new Date(bValue as string).getTime();
      }

      if (aValue === null) aValue = 0;
      if (bValue === null) bValue = 0;

      if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1;
      if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });

    return filtered;
  }, [searchQuery, statusFilter, modelFilter, sortField, sortDirection]);

  // Pagination
  const totalPages = Math.ceil(filteredAndSortedRuns.length / itemsPerPage);
  const paginatedRuns = filteredAndSortedRuns.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  const handleSort = (field: keyof EvaluationRun) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const getStatusBadge = (status: EvaluationRun['status']) => {
    switch (status) {
      case 'completed':
        return <Badge variant="success" size="sm">Completed</Badge>;
      case 'failed':
        return <Badge variant="danger" size="sm">Failed</Badge>;
      case 'running':
        return <Badge variant="warning" size="sm">Running</Badge>;
      case 'pending':
        return <Badge variant="secondary" size="sm">Pending</Badge>;
      default:
        return <Badge variant="secondary" size="sm">Unknown</Badge>;
    }
  };

  const getProgressBar = (processed: number, total: number) => {
    const percentage = total > 0 ? (processed / total) * 100 : 0;
    return (
      <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
        <div
          className="bg-primary-600 h-2 rounded-full transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    );
  };

  // Get unique models for filter
  const uniqueModels = Array.from(new Set(mockRuns.map(run => run.model)));

  const tableColumns = [
    {
      key: 'name',
      label: 'Name',
      sortable: true,
      render: (run: EvaluationRun) => (
        <div>
          <Link href={`/runs/${run.id}`} className="font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300">
            {run.name}
          </Link>
          <div className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            {run.dataset}
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      sortable: true,
      render: (run: EvaluationRun) => (
        <div className="space-y-2">
          {getStatusBadge(run.status)}
          {run.status === 'running' && (
            <div className="space-y-1">
              {getProgressBar(run.itemsProcessed, run.totalItems)}
              <div className="text-xs text-neutral-500 dark:text-neutral-400">
                {run.itemsProcessed}/{run.totalItems} items
              </div>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'model',
      label: 'Model',
      sortable: true,
      render: (run: EvaluationRun) => (
        <div>
          <div className="font-medium text-neutral-900 dark:text-white">
            {run.model}
          </div>
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            {run.metrics.join(', ')}
          </div>
        </div>
      ),
    },
    {
      key: 'score',
      label: 'Score',
      sortable: true,
      render: (run: EvaluationRun) => (
        <div>
          {run.score !== null ? (
            <div className="text-lg font-semibold text-neutral-900 dark:text-white">
              {(run.score * 100).toFixed(1)}%
            </div>
          ) : (
            <span className="text-neutral-400 dark:text-neutral-500">-</span>
          )}
        </div>
      ),
    },
    {
      key: 'timestamp',
      label: 'Created',
      sortable: true,
      render: (run: EvaluationRun) => (
        <div>
          <div className="text-sm text-neutral-900 dark:text-white">
            {formatTimestamp(run.timestamp)}
          </div>
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            Duration: {run.duration}
          </div>
        </div>
      ),
    },
    {
      key: 'actions',
      label: 'Actions',
      sortable: false,
      render: (run: EvaluationRun) => (
        <div className="flex items-center gap-2">
          <Link href={`/runs/${run.id}`}>
            <Button variant="ghost" size="sm">
              View
            </Button>
          </Link>
          <Button variant="ghost" size="sm">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
            </svg>
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="flex-1 overflow-auto">
      <Container className="py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
              Evaluation Runs
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
          </div>
        </div>

        {/* Filters */}
        <Card className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Search
              </label>
              <Input
                type="text"
                placeholder="Search runs, datasets, models..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Status
              </label>
              <Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                options={[
                  { value: 'all', label: 'All Statuses' },
                  { value: 'completed', label: 'Completed' },
                  { value: 'running', label: 'Running' },
                  { value: 'failed', label: 'Failed' },
                  { value: 'pending', label: 'Pending' },
                ]}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Model
              </label>
              <Select
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                options={[
                  { value: 'all', label: 'All Models' },
                  ...uniqueModels.map(model => ({ value: model, label: model })),
                ]}
              />
            </div>

            <div className="flex items-end">
              <Button
                variant="secondary"
                size="md"
                onClick={() => {
                  setSearchQuery('');
                  setStatusFilter('all');
                  setModelFilter('all');
                  setCurrentPage(1);
                }}
                className="w-full"
              >
                Clear Filters
              </Button>
            </div>
          </div>
        </Card>

        {/* Results Summary */}
        <div className="flex items-center justify-between text-sm text-neutral-600 dark:text-neutral-300">
          <span>
            Showing {paginatedRuns.length} of {filteredAndSortedRuns.length} runs
          </span>
          <div className="flex items-center gap-4">
            <span>Sort by:</span>
            <Select
              value={sortField}
              onChange={(e) => setSortField(e.target.value as keyof EvaluationRun)}
              options={[
                { value: 'timestamp', label: 'Created Date' },
                { value: 'name', label: 'Name' },
                { value: 'score', label: 'Score' },
                { value: 'status', label: 'Status' },
              ]}
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')}
            >
              <svg
                className={`w-4 h-4 transition-transform ${sortDirection === 'desc' ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
              </svg>
            </Button>
          </div>
        </div>

        {/* Table */}
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-neutral-200 dark:border-neutral-700">
                <tr>
                  {tableColumns.map((column) => (
                    <th
                      key={column.key}
                      className={cn(
                        'text-left py-3 px-4 font-medium text-neutral-900 dark:text-white',
                        column.sortable && 'cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800'
                      )}
                      onClick={() => column.sortable && handleSort(column.key as keyof EvaluationRun)}
                    >
                      <div className="flex items-center gap-2">
                        {column.label}
                        {column.sortable && sortField === column.key && (
                          <svg
                            className={cn(
                              'w-4 h-4 transition-transform',
                              sortDirection === 'desc' && 'rotate-180'
                            )}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M5 15l7-7 7 7"
                            />
                          </svg>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginatedRuns.map((run, index) => (
                  <tr
                    key={run.id}
                    className={cn(
                      'border-b border-neutral-200 dark:border-neutral-700 hover:bg-neutral-50 dark:hover:bg-neutral-800',
                      index === paginatedRuns.length - 1 && 'border-b-0'
                    )}
                  >
                    {tableColumns.map((column) => (
                      <td key={column.key} className="py-4 px-4">
                        {column.render(run)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between">
            <div className="text-sm text-neutral-600 dark:text-neutral-300">
              Page {currentPage} of {totalPages}
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(currentPage - 1)}
                disabled={currentPage === 1}
              >
                Previous
              </Button>

              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const page = i + 1;
                const isActive = page === currentPage;

                return (
                  <Button
                    key={page}
                    variant={isActive ? "default" : "outline"}
                    size="sm"
                    onClick={() => setCurrentPage(page)}
                  >
                    {page}
                  </Button>
                );
              })}

              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(currentPage + 1)}
                disabled={currentPage === totalPages}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Container>
    </div>
  );
};

export default Runs;
