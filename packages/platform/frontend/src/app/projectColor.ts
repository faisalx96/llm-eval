/**
 * Deterministic identity color for a project, derived from its slug.
 * Uses the categorical chart token palette (never the reserved semantic
 * hues red/green/blue/amber/purple-as-provenance — these are identity
 * dots, drawn from the chart family by design).
 */
const PALETTE = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
] as const

export function projectColor(slug: string): string {
  let hash = 0
  for (let i = 0; i < slug.length; i++) {
    hash = (hash * 31 + slug.charCodeAt(i)) | 0
  }
  return PALETTE[Math.abs(hash) % PALETTE.length]
}
