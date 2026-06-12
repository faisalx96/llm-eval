import type { ComponentType } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import App from '@/App'
import RouteError from '@/app/RouteError'

/**
 * Feature areas are lazy route modules → one chunk per feature. Chunk URLs
 * are resolved at runtime via window.__QYM_ROOT_PATH__ (see renderBuiltUrl
 * in vite.config.ts).
 */
function lazyFeature(loader: () => Promise<{ default: ComponentType }>) {
  return async () => {
    const mod = await loader()
    return { Component: mod.default }
  }
}

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <App />,
      // Shell-level catch-all (404s, render errors outside children).
      errorElement: <RouteError />,
      children: [
        // Child-level error boundary keeps the shell chrome around errors.
        {
          errorElement: <RouteError />,
          children: [
            { index: true, lazy: lazyFeature(() => import('@/features/home/ProjectsHome')) },
            {
              path: 'projects/:slug',
              lazy: lazyFeature(() => import('@/features/runs/RunsPage')),
            },
            {
              path: 'projects/:slug/runs/:runId',
              lazy: lazyFeature(() => import('@/features/run-detail/RunDetailPage')),
            },
            {
              path: 'projects/:slug/compare',
              lazy: lazyFeature(() => import('@/features/compare/ComparePage')),
            },
            {
              path: 'projects/:slug/analysis',
              lazy: lazyFeature(() => import('@/features/analysis/AnalysisPage')),
            },
            {
              path: 'projects/:slug/review',
              lazy: lazyFeature(() => import('@/features/review/ReviewPage')),
            },
            {
              path: 'projects/:slug/datasets',
              lazy: lazyFeature(() => import('@/features/datasets/DatasetsPage')),
            },
            {
              path: 'projects/:slug/datasets/:datasetRef',
              lazy: lazyFeature(() => import('@/features/datasets/DatasetDetailPage')),
            },
            {
              path: 'projects/:slug/settings',
              lazy: lazyFeature(() => import('@/features/settings/SettingsPage')),
            },
            { path: 'admin', lazy: lazyFeature(() => import('@/features/admin/AdminPage')) },
            {
              path: 'profile',
              lazy: lazyFeature(() => import('@/features/profile/ProfilePage')),
            },
            {
              path: '__components',
              lazy: lazyFeature(() => import('@/components/gallery')),
            },
          ],
        },
      ],
    },
  ],
  {
    // The backend may serve the SPA under a non-root prefix (FastAPI
    // root_path); it injects window.__QYM_ROOT_PATH__ before the bundle runs.
    basename: window.__QYM_ROOT_PATH__ || '/',
  },
)
