'use client';

import React, { useState, useMemo } from 'react';
import { Card } from './card';
import { Input } from './input';
import { Button } from './button';
import { Badge } from './badge';
import { Loading } from './loading';
import { Tabs } from './tabs';
import { Textarea } from './textarea';
import { TemplateCard } from './template-card';
import { useTemplates, useTemplateRecommendations } from '@/hooks/useTemplates';
import { EvaluationTemplate } from '@/types';
import { cn } from '@/lib/utils';

interface TemplateMarketplaceProps {
  onSelectTemplate?: (template: EvaluationTemplate) => void;
  selectedTemplateId?: string;
  selectionMode?: boolean;
  showRecommendations?: boolean;
  className?: string;
}

const CATEGORY_INFO = {
  all: {
    label: 'All Templates',
    description: 'Browse all available evaluation templates',
    icon: '📋'
  },
  qa: {
    label: 'Q&A',
    description: 'Templates for question-answering and conversational AI',
    icon: '❓'
  },
  summarization: {
    label: 'Summarization',
    description: 'Templates for text summarization and content condensation',
    icon: '📝'
  },
  classification: {
    label: 'Classification',
    description: 'Templates for text classification and categorization',
    icon: '🏷️'
  },
  general: {
    label: 'General',
    description: 'General-purpose templates for various evaluation tasks',
    icon: '⚙️'
  },
  custom: {
    label: 'Custom',
    description: 'User-created and specialized evaluation templates',
    icon: '🔧'
  }
};

export function TemplateMarketplace({
  onSelectTemplate,
  selectedTemplateId,
  selectionMode = false,
  showRecommendations = true,
  className
}: TemplateMarketplaceProps) {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'popularity' | 'created' | 'name'>('popularity');
  const [showRecommendationPanel, setShowRecommendationPanel] = useState(false);
  const [recommendationInput, setRecommendationInput] = useState('');

  const { templates, templatesByCategory, loading, error, refetch } = useTemplates({
    category: selectedCategory === 'all' ? undefined : selectedCategory,
    search: search.trim() || undefined
  });

  const { 
    recommendations, 
    loading: recommendationLoading, 
    getRecommendations,
    clearRecommendations 
  } = useTemplateRecommendations();

  const filteredAndSortedTemplates = useMemo(() => {
    let filtered = selectedCategory === 'all' ? templates : templatesByCategory[selectedCategory] || [];

    // Sort templates
    filtered = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'popularity':
          return b.popularity_score - a.popularity_score;
        case 'created':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'name':
          return a.display_name.localeCompare(b.display_name);
        default:
          return 0;
      }
    });

    return filtered;
  }, [templates, templatesByCategory, selectedCategory, sortBy]);

  const categoryTabs = Object.entries(CATEGORY_INFO).map(([key, info]) => ({
    value: key,
    label: info.label,
    count: key === 'all' ? templates.length : (templatesByCategory[key]?.length || 0)
  }));

  const handleTemplateSelect = (template: EvaluationTemplate) => {
    onSelectTemplate?.(template);
  };

  const handleGetRecommendations = async () => {
    if (recommendationInput.trim()) {
      await getRecommendations(recommendationInput.trim());
    }
  };

  const handleApplyRecommendedTemplate = (template: EvaluationTemplate) => {
    onSelectTemplate?.(template);
    setShowRecommendationPanel(false);
  };

  if (loading && templates.length === 0) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="text-center py-12">
          <Loading size="lg" text="Loading templates..." />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 text-center">
          <p className="text-red-600 dark:text-red-400 mb-4">
            Failed to load templates: {error.message}
          </p>
          <Button variant="primary" onClick={refetch}>
            Try Again
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
            Template Marketplace
          </h2>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            Choose from pre-built evaluation templates or get AI recommendations
          </p>
        </div>

        <div className="flex items-center gap-3">
          {showRecommendations && (
            <Button
              variant="primary"
              onClick={() => setShowRecommendationPanel(!showRecommendationPanel)}
            >
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              Get AI Recommendations
            </Button>
          )}
          
          <Button variant="neutral" onClick={refetch} disabled={loading}>
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </Button>
        </div>
      </div>

      {/* AI Recommendations Panel */}
      {showRecommendationPanel && (
        <Card className="p-6 bg-gradient-to-br from-primary-50 to-primary-100 dark:from-primary-900/20 dark:to-primary-800/20 border-primary-200 dark:border-primary-800">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-primary-600 rounded-full flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-neutral-900 dark:text-white">
                  AI Template Recommendations
                </h3>
                <p className="text-sm text-neutral-600 dark:text-neutral-300">
                  Describe your evaluation task to get personalized template suggestions
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                  Describe your evaluation task
                </label>
                <Textarea
                  value={recommendationInput}
                  onChange={(e) => setRecommendationInput(e.target.value)}
                  placeholder="e.g., I want to evaluate a chatbot that answers customer support questions about our product..."
                  rows={3}
                />
              </div>

              <div className="flex items-center gap-3">
                <Button
                  variant="primary"
                  onClick={handleGetRecommendations}
                  disabled={!recommendationInput.trim() || recommendationLoading}
                >
                  {recommendationLoading ? (
                    <>
                      <Loading size="sm" className="mr-2" />
                      Analyzing...
                    </>
                  ) : (
                    'Get Recommendations'
                  )}
                </Button>
                
                <Button
                  variant="neutral"
                  onClick={() => {
                    setRecommendationInput('');
                    clearRecommendations();
                  }}
                >
                  Clear
                </Button>
                
                <Button
                  variant="neutral"
                  onClick={() => setShowRecommendationPanel(false)}
                >
                  Close
                </Button>
              </div>
            </div>

            {/* Recommendations Results */}
            {recommendations.length > 0 && (
              <div className="mt-6 pt-6 border-t border-primary-200 dark:border-primary-700">
                <h4 className="font-medium text-neutral-900 dark:text-white mb-4">
                  Recommended Templates ({recommendations.length})
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {recommendations.map((rec, index) => (
                    <div key={index} className="bg-white dark:bg-neutral-800 rounded-lg p-4 border">
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h5 className="font-medium text-neutral-900 dark:text-white">
                            {rec.template.display_name}
                          </h5>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant="success" size="sm">
                              {Math.round(rec.confidence * 100)}% match
                            </Badge>
                            <Badge variant="neutral" size="sm">
                              {rec.template.category}
                            </Badge>
                          </div>
                        </div>
                      </div>
                      
                      <p className="text-sm text-neutral-600 dark:text-neutral-300 mb-3">
                        {rec.template.description}
                      </p>
                      
                      <div className="mb-3">
                        <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">Why recommended:</p>
                        <ul className="text-xs text-neutral-600 dark:text-neutral-300 list-disc list-inside">
                          {rec.reasons.map((reason, idx) => (
                            <li key={idx}>{reason}</li>
                          ))}
                        </ul>
                      </div>
                      
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => handleApplyRecommendedTemplate(rec.template)}
                        className="w-full"
                      >
                        Use This Template
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Search and Filters */}
      <div className="space-y-4">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <Input
              type="text"
              placeholder="Search templates by name, description, or use case..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leftIcon={
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              }
              rightElement={
                search && (
                  <button
                    onClick={() => setSearch('')}
                    className="text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )
              }
            />
          </div>
          
          <div>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'popularity' | 'created' | 'name')}
              className="px-3 py-2 border border-neutral-200 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-800 text-neutral-900 dark:text-white"
            >
              <option value="popularity">Sort by Popularity</option>
              <option value="created">Sort by Newest</option>
              <option value="name">Sort by Name</option>
            </select>
          </div>
        </div>

        <Tabs
          value={selectedCategory}
          onValueChange={setSelectedCategory}
          tabs={categoryTabs.map(tab => ({
            value: tab.value,
            label: `${tab.label} (${tab.count})`,
            disabled: tab.count === 0
          }))}
        />
      </div>

      {/* Category Description */}
      {selectedCategory !== 'all' && (
        <Card className="p-4 bg-neutral-50 dark:bg-neutral-800">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{CATEGORY_INFO[selectedCategory as keyof typeof CATEGORY_INFO]?.icon}</span>
            <div>
              <h3 className="font-medium text-neutral-900 dark:text-white">
                {CATEGORY_INFO[selectedCategory as keyof typeof CATEGORY_INFO]?.label} Templates
              </h3>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                {CATEGORY_INFO[selectedCategory as keyof typeof CATEGORY_INFO]?.description}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Results Summary */}
      {filteredAndSortedTemplates.length > 0 && (
        <div className="flex items-center justify-between text-sm text-neutral-500 dark:text-neutral-400">
          <span>
            Showing {filteredAndSortedTemplates.length} template{filteredAndSortedTemplates.length !== 1 ? 's' : ''}
            {search && ` matching "${search}"`}
          </span>
        </div>
      )}

      {/* Empty State */}
      {filteredAndSortedTemplates.length === 0 && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 bg-neutral-100 dark:bg-neutral-800 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
            No templates found
          </h3>
          <p className="text-neutral-500 dark:text-neutral-400 mb-4">
            {search 
              ? `No templates match "${search}". Try adjusting your search terms.`
              : 'No templates available in this category.'
            }
          </p>
          <div className="flex justify-center gap-3">
            {search && (
              <Button variant="neutral" onClick={() => setSearch('')}>
                Clear Search
              </Button>
            )}
            {showRecommendations && (
              <Button variant="primary" onClick={() => setShowRecommendationPanel(true)}>
                Get AI Recommendations
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Templates Grid */}
      {filteredAndSortedTemplates.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredAndSortedTemplates.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              onSelect={handleTemplateSelect}
              isSelected={template.id === selectedTemplateId}
              selectionMode={selectionMode}
            />
          ))}
        </div>
      )}
    </div>
  );
}