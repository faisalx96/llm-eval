'use client';

// import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { useState } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { SidebarLayout, type SidebarItem } from '@/components/layout/sidebar';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

// Note: metadata is handled differently in client components
// export const metadata: Metadata = {
//   title: 'LLM-Eval',
//   description: 'UI-first LLM evaluation platform',
// };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pathname = usePathname();

  // Navigation items
  const navigationItems: SidebarItem[] = [
    {
      id: 'dashboard',
      label: 'Run Browser',
      href: '/dashboard',
      active: pathname === '/dashboard' || pathname.startsWith('/dashboard'),
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5a2 2 0 012-2h4a2 2 0 012 2v2H8V5z" />
        </svg>
      ),
    },
    {
      id: 'new-run',
      label: 'New Evaluation',
      href: '/runs/new',
      active: pathname === '/runs/new',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
        </svg>
      ),
    },
    {
      id: 'compare',
      label: 'Compare Runs',
      href: '/compare',
      active: pathname === '/compare',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
    },
    {
      id: 'divider-1',
      label: '',
      href: '',
      active: false,
      icon: <div className="w-full h-px bg-neutral-200 dark:bg-neutral-700 my-2" />,
    },
    {
      id: 'templates',
      label: 'Templates',
      href: '/templates',
      active: pathname === '/templates',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
    },
    {
      id: 'components',
      label: 'Components',
      href: '/components',
      active: pathname === '/components',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
    },
    {
      id: 'settings',
      label: 'Settings',
      href: '/settings',
      active: pathname === '/settings',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
  ];

  // Header component
  const sidebarHeader = (
    <div className="flex items-center gap-3">
      {!sidebarCollapsed && (
        <>
          <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">LE</span>
          </div>
          <div>
            <h1 className="font-semibold text-lg text-neutral-900 dark:text-white">LLM-Eval</h1>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">v0.3.0</p>
          </div>
        </>
      )}
      {sidebarCollapsed && (
        <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center mx-auto">
          <span className="text-white font-bold text-sm">LE</span>
        </div>
      )}
    </div>
  );

  // Footer component with user menu
  const sidebarFooter = (
    <div className="space-y-2">
      {!sidebarCollapsed && (
        <div className="flex items-center gap-3 p-2 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div className="w-8 h-8 bg-gradient-to-br from-primary-500 to-primary-600 rounded-full flex items-center justify-center">
            <span className="text-white font-medium text-sm">U</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-neutral-900 dark:text-white truncate">Developer</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400 truncate">dev@example.com</p>
          </div>
        </div>
      )}
      {sidebarCollapsed && (
        <div className="w-8 h-8 bg-gradient-to-br from-primary-500 to-primary-600 rounded-full flex items-center justify-center mx-auto">
          <span className="text-white font-medium text-sm">U</span>
        </div>
      )}
    </div>
  );

  // Custom navigation renderer for Next.js Links
  const renderNavigation = () => (
    <div className="flex-1 p-3 space-y-1 overflow-y-auto">
      {navigationItems.map((item) => {
        // Handle divider items
        if (item.id.startsWith('divider')) {
          return (
            <div key={item.id} className="px-3 py-2">
              {item.icon}
            </div>
          );
        }

        // Handle regular navigation items
        return (
          <Link key={item.id} href={item.href || '#'}>
            <div
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors cursor-pointer',
                'hover:bg-neutral-100 dark:hover:bg-neutral-800',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
                item.active && 'bg-primary-50 text-primary-700 dark:bg-primary-900/50 dark:text-primary-300',
                !item.active && 'text-neutral-700 dark:text-neutral-300',
                sidebarCollapsed && 'justify-center px-2'
              )}
            >
              {item.icon && (
                <span className={cn('flex-shrink-0', sidebarCollapsed ? 'text-lg' : 'text-base')}>
                  {item.icon}
                </span>
              )}
              
              {!sidebarCollapsed && (
                <>
                  <span className="flex-1 text-left truncate">{item.label}</span>
                  {item.badge && (
                    <span className="flex-shrink-0">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
            </div>
          </Link>
        );
      })}
    </div>
  );

  return (
    <html lang="en">
      <head>
        <title>LLM-Eval - UI-first LLM Evaluation Platform</title>
        <meta name="description" content="UI-first LLM evaluation platform for technical developers" />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <SidebarLayout
          sidebarCollapsed={sidebarCollapsed}
          sidebar={
            <div
              className={cn(
                'flex flex-col h-full bg-white dark:bg-neutral-900 border-r border-neutral-200 dark:border-neutral-700 transition-all duration-300',
                sidebarCollapsed ? 'w-16' : 'w-64'
              )}
            >
              {/* Header */}
              <div className={cn(
                'flex-shrink-0 px-4 py-4 border-b border-neutral-200 dark:border-neutral-700',
                sidebarCollapsed && 'px-2'
              )}>
                {sidebarHeader}
              </div>

              {/* Navigation Items */}
              {renderNavigation()}

              {/* Footer */}
              <div className={cn(
                'flex-shrink-0 p-4 border-t border-neutral-200 dark:border-neutral-700',
                sidebarCollapsed && 'px-2'
              )}>
                {sidebarFooter}
              </div>

              {/* Toggle Button */}
              <button
                onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                className={cn(
                  'absolute top-4 -right-3 w-6 h-6 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-full flex items-center justify-center shadow-sm',
                  'hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2'
                )}
                aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              >
                <svg
                  className={cn(
                    'w-3 h-3 transition-transform',
                    sidebarCollapsed && 'rotate-180'
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
            </div>
          }
        >
          {children}
        </SidebarLayout>
      </body>
    </html>
  );
}
