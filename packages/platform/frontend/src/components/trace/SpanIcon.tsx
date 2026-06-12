import {
  AlertCircle,
  Bot,
  Database,
  Link2,
  LayoutGrid,
  MessageSquare,
  Star,
  Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { SPAN_KIND_HUES } from '@/lib/trace'
import type { SpanKind } from '@/lib/trace'
import { cn } from '@/lib/cn'
import styles from './TraceDrawer.module.css'

/**
 * Kind icon for a span row / detail header. Replaces the legacy inline SVG
 * set (trace_viewer.js ICONS, L36-45) with the app's lucide equivalents:
 * chat bubble (LLM), wrench (TOOL), agent (AGENT), chain links (CHAIN),
 * star (EVALUATOR), database (RETRIEVER), grid (EMBED).
 * Colors come from SPAN_KIND_HUES (existing tokens only).
 */
const KIND_ICONS: Record<SpanKind, LucideIcon> = {
  LLM: MessageSquare,
  TOOL: Wrench,
  AGENT: Bot,
  CHAIN: Link2,
  EVALUATOR: Star,
  RETRIEVER: Database,
  EMBED: LayoutGrid,
  DEFAULT: AlertCircle,
}

/** Human label for the detail header (sentence case). */
export const KIND_LABELS: Record<SpanKind, string> = {
  LLM: 'LLM',
  TOOL: 'Tool',
  AGENT: 'Agent',
  CHAIN: 'Chain',
  EVALUATOR: 'Evaluator',
  RETRIEVER: 'Retriever',
  EMBED: 'Embedding',
  DEFAULT: 'Span',
}

export function SpanIcon({ kind, className }: { kind: SpanKind; className?: string }) {
  const Icon = kind === 'DEFAULT' ? null : KIND_ICONS[kind]
  return (
    <span
      className={cn(styles.kindIcon, className)}
      style={{ color: SPAN_KIND_HUES[kind] }}
      aria-hidden="true"
    >
      {Icon ? <Icon /> : <span className={styles.kindDot} />}
    </span>
  )
}
