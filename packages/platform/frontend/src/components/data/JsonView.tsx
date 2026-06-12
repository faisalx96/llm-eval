import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import styles from './JsonView.module.css'

/**
 * Recursive collapsible JSON tree. All values render as plain React text
 * nodes (never markup), so untrusted payloads are inert by construction.
 * Object/array nodes collapse via real <button>s — keyboard-expandable for
 * free (Enter/Space), with aria-expanded state.
 */

export interface JsonViewProps {
  value: unknown
  /** Nodes at depth < this start expanded. Default 2. */
  defaultExpandDepth?: number
  className?: string
}

export function JsonView({ value, defaultExpandDepth = 2, className }: JsonViewProps) {
  return (
    <div className={cn(styles.root, className)}>
      <JsonNode value={value} depth={0} defaultExpandDepth={defaultExpandDepth} />
    </div>
  )
}

interface JsonNodeProps {
  name?: string
  value: unknown
  depth: number
  defaultExpandDepth: number
  trailingComma?: boolean
}

function isComposite(v: unknown): v is object {
  return typeof v === 'object' && v !== null
}

function JsonNode({ name, value, depth, defaultExpandDepth, trailingComma }: JsonNodeProps) {
  const composite = isComposite(value)
  const [open, setOpen] = useState(depth < defaultExpandDepth)

  const indent = { paddingLeft: depth * 14 }
  const keyPart =
    name !== undefined ? (
      <>
        <span className={styles.key}>{JSON.stringify(name)}</span>
        <span className={styles.punct}>: </span>
      </>
    ) : null
  const comma = trailingComma ? <span className={styles.punct}>,</span> : null

  if (!composite) {
    return (
      <div className={styles.line} style={indent}>
        <span className={styles.toggleSpacer} aria-hidden="true" />
        {keyPart}
        <Primitive value={value} />
        {comma}
      </div>
    )
  }

  const isArr = Array.isArray(value)
  const entries: ReadonlyArray<readonly [string | undefined, unknown]> = isArr
    ? (value as unknown[]).map((v) => [undefined, v] as const)
    : Object.entries(value as Record<string, unknown>)
  const openBracket = isArr ? '[' : '{'
  const closeBracket = isArr ? ']' : '}'
  const count = entries.length

  // Empty containers render as a plain "{}" / "[]" line — nothing to expand.
  if (count === 0) {
    return (
      <div className={styles.line} style={indent}>
        <span className={styles.toggleSpacer} aria-hidden="true" />
        {keyPart}
        <span className={styles.punct}>
          {openBracket}
          {closeBracket}
        </span>
        {comma}
      </div>
    )
  }

  const noun = isArr ? (count === 1 ? 'item' : 'items') : count === 1 ? 'key' : 'keys'

  return (
    <div>
      <div className={styles.line} style={indent}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={open}
          aria-label={`${open ? 'Collapse' : 'Expand'} ${name ?? 'value'}`}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? (
            <ChevronDown size={11} aria-hidden="true" />
          ) : (
            <ChevronRight size={11} aria-hidden="true" />
          )}
        </button>
        {keyPart}
        <span className={styles.punct}>{openBracket}</span>
        {!open && (
          <>
            <span className={styles.summary}>{` ${count} ${noun} `}</span>
            <span className={styles.punct}>{closeBracket}</span>
            {comma}
          </>
        )}
      </div>
      {open && (
        <>
          {entries.map(([k, v], i) => (
            <JsonNode
              key={k ?? i}
              name={k}
              value={v}
              depth={depth + 1}
              defaultExpandDepth={defaultExpandDepth}
              trailingComma={i < count - 1}
            />
          ))}
          <div className={styles.line} style={indent}>
            <span className={styles.toggleSpacer} aria-hidden="true" />
            <span className={styles.punct}>
              {closeBracket}
              {trailingComma ? ',' : ''}
            </span>
          </div>
        </>
      )}
    </div>
  )
}

function Primitive({ value }: { value: unknown }) {
  if (typeof value === 'string') {
    return <span className={styles.string}>{JSON.stringify(value)}</span>
  }
  if (typeof value === 'number' || typeof value === 'bigint') {
    return <span className={styles.number}>{String(value)}</span>
  }
  if (typeof value === 'boolean') {
    return <span className={styles.keyword}>{String(value)}</span>
  }
  if (value === null) {
    return <span className={styles.keyword}>null</span>
  }
  return <span className={styles.string}>{String(value)}</span>
}
