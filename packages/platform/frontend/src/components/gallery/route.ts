import type { ComponentType } from 'react'
import GalleryPage from './GalleryPage'

export interface GalleryRouteMeta {
  path: string
  Component: ComponentType
}

/**
 * Route metadata for the dev-only component gallery.
 * The app-shell agent wires this into router.tsx (file ownership:
 * this package must not edit the router).
 */
export const galleryRoute: GalleryRouteMeta = {
  path: '/__components',
  Component: GalleryPage,
}

export default galleryRoute
