'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface SkeletonProps {
  className?: string;
  animate?: boolean;
}

export const SkeletonBox: React.FC<SkeletonProps> = ({
  className,
  animate = true
}) => {
  return (
    <div
      className={cn(
        'bg-neutral-200 dark:bg-neutral-700 rounded',
        animate && 'animate-pulse',
        className
      )}
    />
  );
};

// Specialized skeleton components for common use cases

export const RunDetailSkeleton: React.FC = () => {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <SkeletonBox className="w-6 h-6" />
          <SkeletonBox className="h-8 w-48" />
          <SkeletonBox className="h-6 w-20" />
        </div>
        <SkeletonBox className="h-4 w-64" />
        <div className="flex items-center gap-4">
          <SkeletonBox className="h-3 w-32" />
          <SkeletonBox className="h-3 w-24" />
          <SkeletonBox className="h-3 w-28" />
        </div>
      </div>

      {/* Progress bar skeleton */}
      <div className="border border-neutral-200 dark:border-neutral-700 rounded-lg p-6">
        <div className="flex items-center justify-between mb-3">
          <SkeletonBox className="h-6 w-40" />
          <SkeletonBox className="h-4 w-32" />
        </div>
        <SkeletonBox className="h-3 w-full rounded-full" />
        <div className="flex justify-between mt-2">
          <SkeletonBox className="h-3 w-20" />
          <SkeletonBox className="h-3 w-16" />
        </div>
      </div>

      {/* Tabs skeleton */}
      <div className="border border-neutral-200 dark:border-neutral-700 rounded-lg">
        <div className="flex border-b border-neutral-200 dark:border-neutral-700">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonBox key={i} className="h-10 w-20 m-2" />
          ))}
        </div>
        <div className="p-6 space-y-6">
          {/* Stats grid skeleton */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                <SkeletonBox className="h-3 w-16 mb-2" />
                <SkeletonBox className="h-8 w-12" />
              </div>
            ))}
          </div>

          {/* Content skeleton */}
          <div className="space-y-4">
            <SkeletonBox className="h-6 w-32" />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex justify-between">
                    <SkeletonBox className="h-4 w-20" />
                    <SkeletonBox className="h-4 w-24" />
                  </div>
                ))}
              </div>
              <div className="space-y-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex justify-between">
                    <SkeletonBox className="h-4 w-20" />
                    <SkeletonBox className="h-4 w-24" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export const MetricsSkeleton: React.FC = () => {
  return (
    <div className="space-y-6">
      {/* Overall scores skeleton */}
      <div>
        <SkeletonBox className="h-6 w-40 mb-4" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
              <SkeletonBox className="h-3 w-24 mb-2" />
              <SkeletonBox className="h-8 w-16" />
            </div>
          ))}
        </div>
      </div>

      {/* Detailed metrics skeleton */}
      <div>
        <SkeletonBox className="h-6 w-32 mb-4" />
        
        {/* Chart skeleton */}
        <div className="mb-6">
          <SkeletonBox className="h-5 w-40 mb-3" />
          <div className="space-y-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <SkeletonBox className="h-4 w-32" />
                  <div className="flex items-center gap-4">
                    <SkeletonBox className="h-4 w-12" />
                    <SkeletonBox className="h-3 w-8" />
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between mb-1">
                    <SkeletonBox className="h-3 w-8" />
                    <SkeletonBox className="h-3 w-12" />
                  </div>
                  <SkeletonBox className="h-2 w-full rounded-full" />
                  <div className="flex items-center justify-between mb-1">
                    <SkeletonBox className="h-3 w-12" />
                    <SkeletonBox className="h-3 w-12" />
                  </div>
                  <SkeletonBox className="h-2 w-full rounded-full" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export const RunItemsTableSkeleton: React.FC = () => {
  return (
    <div className="space-y-4">
      {/* Filters skeleton */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex items-center gap-2">
            <SkeletonBox className="h-4 w-12" />
            <SkeletonBox className="h-10 w-24" />
          </div>
          <div className="flex items-center gap-2">
            <SkeletonBox className="h-4 w-16" />
            <SkeletonBox className="h-10 w-16" />
          </div>
        </div>
        <SkeletonBox className="h-4 w-48" />
      </div>

      {/* Table skeleton */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-neutral-50 dark:bg-neutral-900/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr>
                {Array.from({ length: 5 }).map((_, i) => (
                  <th key={i} className="px-4 py-3 text-left">
                    <SkeletonBox className="h-4 w-16" />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
              {Array.from({ length: 10 }).map((_, i) => (
                <tr key={i} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50">
                  <td className="px-4 py-3">
                    <SkeletonBox className="h-4 w-20 mb-1" />
                    <SkeletonBox className="h-3 w-32" />
                  </td>
                  <td className="px-4 py-3">
                    <SkeletonBox className="h-5 w-16" />
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-1">
                      <SkeletonBox className="h-3 w-24" />
                      <SkeletonBox className="h-3 w-20" />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-1">
                      <SkeletonBox className="h-3 w-20" />
                      <SkeletonBox className="h-3 w-16" />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <SkeletonBox className="h-8 w-16" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination skeleton */}
        <div className="px-4 py-3 border-t border-neutral-200 dark:border-neutral-700 flex items-center justify-between">
          <SkeletonBox className="h-4 w-24" />
          <div className="flex items-center gap-2">
            <SkeletonBox className="h-8 w-20" />
            <SkeletonBox className="h-8 w-16" />
          </div>
        </div>
      </div>
    </div>
  );
};