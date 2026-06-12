import { StatCard } from '@/components/data'
import { docsUrl, type RunDetail } from '@/api/runDetail'
import { fmtMs, fmtPercent, fmtTokens } from '@/lib/format'
import { isTraceStatsEmpty } from './lib'
import styles from './TraceStatsSection.module.css'

interface Tile {
  label: string
  value: string
}

function num(stats: Record<string, unknown>, key: string): number | null {
  const value = stats[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function buildTiles(stats: Record<string, unknown>): Tile[] {
  const tiles: Tile[] = []
  const push = (label: string, raw: number | null, format: (n: number) => string) => {
    if (raw !== null && raw !== 0) tiles.push({ label, value: format(raw) })
  }
  push('Avg tokens', num(stats, 'avg_tokens'), fmtTokens)
  push('Avg LLM calls', num(stats, 'avg_llm_calls'), (n) => n.toFixed(1))
  push('Avg tool calls', num(stats, 'avg_tool_calls'), (n) => n.toFixed(1))
  push('Tool success', num(stats, 'tool_success_rate'), fmtPercent)
  push('Avg LLM time', num(stats, 'avg_llm_ms'), fmtMs)
  push('Avg tool time', num(stats, 'avg_tool_ms'), fmtMs)
  push('Malformed tool calls', num(stats, 'total_malformed_tool_calls'), String)
  push('Provider errors', num(stats, 'total_provider_errors'), String)
  return tiles
}

/**
 * Trace stats: a compact tile grid when the task is instrumented; a single
 * quiet hint line when it is not (all of tokens/LLM calls/tool calls 0/null).
 */
export function TraceStatsSection({ run }: { run: RunDetail }) {
  if (isTraceStatsEmpty(run.trace_stats)) {
    return (
      <p className={styles.empty}>
        No trace data — this task isn&apos;t instrumented.{' '}
        <a className={styles.docsLink} href={docsUrl()} target="_blank" rel="noreferrer">
          Add qym tracing →
        </a>
      </p>
    )
  }

  const tiles = buildTiles((run.trace_stats ?? {}) as Record<string, unknown>)
  if (tiles.length === 0) return null

  return (
    <section className={styles.grid} aria-label="Trace stats">
      {tiles.map((tile) => (
        <StatCard key={tile.label} className={styles.card} label={tile.label} value={tile.value} />
      ))}
    </section>
  )
}
