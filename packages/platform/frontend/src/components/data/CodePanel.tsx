import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/cn'
import { diffWords } from './diff'
import { JsonView } from './JsonView'
import styles from './CodePanel.module.css'

/**
 * Mono panel for inputs/outputs/SQL/JSON.
 *
 * Safety: content renders STRICTLY through React text nodes (string children
 * of <pre>/<span>) — never innerHTML — so untrusted model output is inert.
 *
 * JSON whose text parses cleanly is auto-pretty-printed as a collapsible
 * tree (JsonView). Pass `detectJson={false}` to force raw text.
 *
 * Diff mode: pass `diff={{ a, b }}` to render an inline word diff of a → b
 * (deletions/insertions tinted with the reserved fail/pass hues at low alpha).
 */

export type CodePanelTone = 'neutral' | 'pass' | 'fail' | 'info' | 'warn' | 'ai'

export interface CodePanelProps {
  /** Raw text content. Ignored when `diff` is provided. */
  code?: string
  /** Optional header label, e.g. "Output" / "Expected". */
  label?: string
  /**
   * Label tinting — subtle left border + label color only (never a solid
   * colored block). pass/fail use the reserved outcome hues; info = running,
   * warn = needs attention, ai = AI provenance.
   */
  tone?: CodePanelTone
  /** Collapsed max body height in px before "Show more" appears. Default 320. */
  maxHeight?: number
  /** Show the copy button. Default true. */
  copyable?: boolean
  /** Auto-detect + pretty-print JSON. Default true. */
  detectJson?: boolean
  /** Initial expand depth for detected JSON trees. */
  jsonExpandDepth?: number
  /** Inline word-diff mode: highlights b's insertions and a's deletions. */
  diff?: { a: string; b: string }
  /** Override the text placed on the clipboard. */
  copyText?: string
  className?: string
}

type ParseResult = { ok: true; value: unknown } | { ok: false }

function tryParseJson(text: string): ParseResult {
  const t = text.trim()
  if (!t || (t[0] !== '{' && t[0] !== '[')) return { ok: false }
  try {
    return { ok: true, value: JSON.parse(t) as unknown }
  } catch {
    return { ok: false }
  }
}

export function CodePanel({
  code,
  label,
  tone = 'neutral',
  maxHeight = 320,
  copyable = true,
  detectJson = true,
  jsonExpandDepth,
  diff,
  copyText,
  className,
}: CodePanelProps) {
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const [copied, setCopied] = useState(false)
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const copiedTimer = useRef<number | undefined>(undefined)

  const parsed = useMemo<ParseResult>(
    () => (detectJson && !diff && code != null ? tryParseJson(code) : { ok: false }),
    [detectJson, diff, code],
  )

  useLayoutEffect(() => {
    const el = bodyRef.current
    if (!el) return
    setOverflowing(el.scrollHeight > maxHeight + 1)
  }, [code, diff, parsed, maxHeight])

  useLayoutEffect(() => () => window.clearTimeout(copiedTimer.current), [])

  const handleCopy = async (): Promise<void> => {
    const text = copyText ?? (diff ? diff.b : code) ?? ''
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.clearTimeout(copiedTimer.current)
      copiedTimer.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable (permissions / insecure context) — no-op.
    }
  }

  const showHeader = Boolean(label) || copyable

  return (
    <div className={cn(styles.panel, styles[`tone_${tone}`], className)}>
      {showHeader && (
        <div className={styles.header}>
          {label ? <span className={styles.label}>{label}</span> : <span />}
          {copyable && (
            <button
              type="button"
              className={styles.copyBtn}
              onClick={() => void handleCopy()}
              aria-label={copied ? 'Copied to clipboard' : 'Copy to clipboard'}
            >
              {copied ? (
                <Check size={12} aria-hidden="true" />
              ) : (
                <Copy size={12} aria-hidden="true" />
              )}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}
        </div>
      )}
      <div
        ref={bodyRef}
        className={styles.body}
        style={expanded ? undefined : { maxHeight }}
      >
        {diff ? (
          <DiffView a={diff.a} b={diff.b} />
        ) : parsed.ok ? (
          <JsonView
            value={parsed.value}
            defaultExpandDepth={jsonExpandDepth}
            className={styles.jsonBody}
          />
        ) : (
          <pre className={styles.pre}>{code}</pre>
        )}
        {!expanded && overflowing && <div className={styles.fade} aria-hidden="true" />}
      </div>
      {(overflowing || expanded) && (
        <button
          type="button"
          className={styles.expandBtn}
          aria-expanded={expanded}
          onClick={() => setExpanded((x) => !x)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}

function DiffView({ a, b }: { a: string; b: string }) {
  const segments = useMemo(() => diffWords(a, b), [a, b])
  return (
    <pre className={styles.pre}>
      {segments.map((s, i) =>
        s.type === 'equal' ? (
          <span key={i}>{s.text}</span>
        ) : (
          <span
            key={i}
            data-diff={s.type}
            className={s.type === 'ins' ? styles.ins : styles.del}
          >
            {s.text}
          </span>
        ),
      )}
    </pre>
  )
}
