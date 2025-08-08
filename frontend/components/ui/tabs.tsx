import React from 'react';
import { cn } from '@/lib/utils';

export interface TabItem {
  id: string;
  label: string;
  content: React.ReactNode;
  disabled?: boolean;
  badge?: React.ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  defaultTab?: string;
  activeTab?: string;
  onTabChange?: (tabId: string) => void;
  variant?: 'default' | 'pills' | 'underline';
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
  className?: string;
}

const Tabs: React.FC<TabsProps> = ({
  items,
  defaultTab,
  activeTab: controlledActiveTab,
  onTabChange,
  variant = 'default',
  size = 'md',
  fullWidth = false,
  className,
}) => {
  const [internalActiveTab, setInternalActiveTab] = React.useState(
    defaultTab || items[0]?.id || ''
  );

  const activeTab = controlledActiveTab ?? internalActiveTab;
  const isControlled = controlledActiveTab !== undefined;

  const handleTabClick = (tabId: string) => {
    if (!isControlled) {
      setInternalActiveTab(tabId);
    }
    onTabChange?.(tabId);
  };

  const activeTabItem = items.find(item => item.id === activeTab);

  const getTabListClasses = () => {
    const baseClasses = 'flex border-b border-neutral-200 dark:border-neutral-700';

    if (variant === 'pills') {
      return 'flex p-1 bg-neutral-100 dark:bg-neutral-800 rounded-lg';
    }

    if (fullWidth) {
      return cn(baseClasses, 'w-full');
    }

    return baseClasses;
  };

  const getTabClasses = (item: TabItem, isActive: boolean) => {
    const sizeClasses = {
      sm: 'px-3 py-1.5 text-xs',
      md: 'px-4 py-2 text-sm',
      lg: 'px-6 py-3 text-base',
    };

    const baseClasses = cn(
      'inline-flex items-center gap-2 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
      sizeClasses[size],
      item.disabled && 'opacity-50 cursor-not-allowed',
      !item.disabled && 'cursor-pointer',
      fullWidth && 'flex-1 justify-center'
    );

    if (variant === 'pills') {
      return cn(
        baseClasses,
        'rounded-md',
        isActive
          ? 'bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 shadow-sm'
          : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100'
      );
    }

    if (variant === 'underline') {
      return cn(
        baseClasses,
        'border-b-2 pb-2',
        isActive
          ? 'border-primary-500 text-primary-600 dark:text-primary-400'
          : 'border-transparent text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100 hover:border-neutral-300'
      );
    }

    // Default variant
    return cn(
      baseClasses,
      'border-b-2 -mb-px',
      isActive
        ? 'border-primary-500 text-primary-600 dark:text-primary-400 bg-white dark:bg-neutral-900'
        : 'border-transparent text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100 hover:border-neutral-300'
    );
  };

  return (
    <div className={cn('w-full', className)}>
      {/* Tab List */}
      <div
        className={getTabListClasses()}
        role="tablist"
        aria-orientation="horizontal"
      >
        {items.map((item) => {
          const isActive = item.id === activeTab;

          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`tabpanel-${item.id}`}
              id={`tab-${item.id}`}
              tabIndex={isActive ? 0 : -1}
              disabled={item.disabled}
              className={getTabClasses(item, isActive)}
              onClick={() => !item.disabled && handleTabClick(item.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  if (!item.disabled) {
                    handleTabClick(item.id);
                  }
                }
              }}
            >
              <span>{item.label}</span>
              {item.badge && (
                <span className="ml-1">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <div className="mt-4">
        {activeTabItem && (
          <div
            role="tabpanel"
            id={`tabpanel-${activeTabItem.id}`}
            aria-labelledby={`tab-${activeTabItem.id}`}
            tabIndex={0}
          >
            {activeTabItem.content}
          </div>
        )}
      </div>
    </div>
  );
};

export { Tabs };
