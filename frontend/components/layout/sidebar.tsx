import React from 'react';
import { cn } from '@/lib/utils';

export interface SidebarItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  badge?: React.ReactNode;
  children?: SidebarItem[];
}

export interface SidebarProps {
  items: SidebarItem[];
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}

const Sidebar: React.FC<SidebarProps> = ({
  items,
  collapsed = false,
  onToggleCollapse,
  header,
  footer,
  className,
}) => {
  const [expandedItems, setExpandedItems] = React.useState<Set<string>>(new Set());

  const toggleExpanded = (itemId: string) => {
    const newExpanded = new Set(expandedItems);
    if (newExpanded.has(itemId)) {
      newExpanded.delete(itemId);
    } else {
      newExpanded.add(itemId);
    }
    setExpandedItems(newExpanded);
  };

  const renderSidebarItem = (item: SidebarItem, level = 0) => {
    const hasChildren = item.children && item.children.length > 0;
    const isExpanded = expandedItems.has(item.id);
    const Component = item.href ? 'a' : 'button';

    return (
      <div key={item.id} className="w-full">
        <Component
          href={item.href}
          onClick={() => {
            if (hasChildren) {
              toggleExpanded(item.id);
            }
            if (item.onClick) {
              item.onClick();
            }
          }}
          disabled={item.disabled}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors',
            'hover:bg-neutral-100 dark:hover:bg-neutral-800',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
            item.active && 'bg-primary-50 text-primary-700 dark:bg-primary-900/50 dark:text-primary-300',
            item.disabled && 'opacity-50 cursor-not-allowed',
            !item.disabled && !item.active && 'text-neutral-700 dark:text-neutral-300',
            level > 0 && 'ml-6',
            collapsed && 'justify-center px-2'
          )}
        >
          {item.icon && (
            <span className={cn('flex-shrink-0', collapsed ? 'text-lg' : 'text-base')}>
              {item.icon}
            </span>
          )}

          {!collapsed && (
            <>
              <span className="flex-1 text-left truncate">{item.label}</span>

              {item.badge && (
                <span className="flex-shrink-0">
                  {item.badge}
                </span>
              )}

              {hasChildren && (
                <svg
                  className={cn(
                    'flex-shrink-0 w-4 h-4 transition-transform',
                    isExpanded && 'rotate-90'
                  )}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              )}
            </>
          )}
        </Component>

        {/* Children */}
        {hasChildren && isExpanded && !collapsed && (
          <div className="mt-1 space-y-1 pl-6">
            {item.children!.map((child) => renderSidebarItem(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      className={cn(
        'flex flex-col h-full bg-white dark:bg-neutral-900 border-r border-neutral-200 dark:border-neutral-700 transition-all duration-300',
        collapsed ? 'w-16' : 'w-64',
        className
      )}
    >
      {/* Header */}
      {header && (
        <div className={cn(
          'flex-shrink-0 px-4 py-4 border-b border-neutral-200 dark:border-neutral-700',
          collapsed && 'px-2'
        )}>
          {header}
        </div>
      )}

      {/* Navigation Items */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {items.map((item) => renderSidebarItem(item))}
      </nav>

      {/* Footer */}
      {footer && (
        <div className={cn(
          'flex-shrink-0 p-4 border-t border-neutral-200 dark:border-neutral-700',
          collapsed && 'px-2'
        )}>
          {footer}
        </div>
      )}

      {/* Toggle Button */}
      {onToggleCollapse && (
        <button
          onClick={onToggleCollapse}
          className={cn(
            'absolute top-4 -right-3 w-6 h-6 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-full flex items-center justify-center shadow-sm',
            'hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2'
          )}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg
            className={cn(
              'w-3 h-3 transition-transform',
              collapsed && 'rotate-180'
            )}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
        </button>
      )}
    </div>
  );
};

// Sidebar layout wrapper
export interface SidebarLayoutProps {
  children: React.ReactNode;
  sidebar: React.ReactNode;
  sidebarCollapsed?: boolean;
  className?: string;
}

const SidebarLayout: React.FC<SidebarLayoutProps> = ({
  children,
  sidebar,
  sidebarCollapsed = false, // eslint-disable-line @typescript-eslint/no-unused-vars
  className,
}) => {
  return (
    <div className={cn('flex h-screen overflow-hidden', className)}>
      {/* Sidebar */}
      <div className="flex-shrink-0 relative">
        {sidebar}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {children}
      </div>
    </div>
  );
};

export { Sidebar, SidebarLayout };
