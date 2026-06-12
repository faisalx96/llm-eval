import '../ui/testPolyfills'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import GalleryPage from './GalleryPage'
import { galleryRoute } from './route'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('GalleryPage', () => {
  it('renders every component section', () => {
    render(<GalleryPage />)
    for (const section of [
      'Button',
      'StatusBadge — the single status→hue map',
      'Tabs — underline, the one tab paradigm',
      'Tooltip',
      'Toast',
      'ConfirmModal',
      'DropdownMenu — the app kebab menu',
      'Drawer',
      'Skeleton & ProgressBar',
      'EmptyState — the one empty-state contract',
      'CopyChip',
      'pluralize',
    ]) {
      expect(screen.getByRole('heading', { name: section })).toBeInTheDocument()
    }
  })

  it('uses a landmark main with a top-level heading (a11y)', () => {
    render(<GalleryPage />)
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Component gallery' })).toBeInTheDocument()
  })

  it('exports route metadata for the shell agent to wire', () => {
    expect(galleryRoute.path).toBe('/__components')
    expect(galleryRoute.Component).toBe(GalleryPage)
  })
})
