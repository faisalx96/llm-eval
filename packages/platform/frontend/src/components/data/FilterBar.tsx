import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import * as Popover from '@radix-ui/react-popover'
import { ListFilter, Search, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import styles from './FilterBar.module.css'

/**
 * Composable filter bar: debounced search, facet popover, removable active
 * chips, "Clear all", and a segmented time quick-toggle.
 *
 * Fully controlled via `value` / `onChange` with the shape
 * `{ q, facets: Record<string, string[]>, time }`.
 */

export type TimeKey = 'all' | 'today' | '7d' | '30d' | 'custom'

export interface FilterBarState {
  q: string
  facets: Record<string, string[]>
  time: TimeKey
}

export interface FacetOption {
  value: string
  label?: string
}

export interface FacetConfig {
  id: string
  label: string
  /** Static options. */
  options?: FacetOption[]
  /** Async options, loaded once when the popover first opens. */
  loadOptions?: () => Promise<FacetOption[]>
}

export interface FilterBarProps {
  value: FilterBarState
  onChange: (next: FilterBarState) => void
  facets?: FacetConfig[]
  searchPlaceholder?: string
  /** Debounce for search input → onChange. Default 250ms. */
  debounceMs?: number
  /** Hide the time quick-toggle. Default shown. */
  showTime?: boolean
  /** Rendered after the segmented control while `time === 'custom'` (caller-owned range picker). */
  customTimeSlot?: ReactNode
  /** Free slot at the trailing edge of the bar. */
  end?: ReactNode
  className?: string
}

export const EMPTY_FILTER_STATE: FilterBarState = { q: '', facets: {}, time: 'all' }

const TIME_OPTIONS: ReadonlyArray<{ key: TimeKey; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: 'custom', label: 'Custom' },
]

type AsyncOptionsState = Record<string, FacetOption[] | 'loading' | 'error'>

export function FilterBar({
  value,
  onChange,
  facets = [],
  searchPlaceholder = 'Search',
  debounceMs = 250,
  showTime = true,
  customTimeSlot,
  end,
  className,
}: FilterBarProps) {
  const [localQ, setLocalQ] = useState(value.q)
  const [open, setOpen] = useState(false)
  const [asyncOptions, setAsyncOptions] = useState<AsyncOptionsState>({})
  const startedLoads = useRef(new Set<string>())
  const debounceTimer = useRef<number | undefined>(undefined)

  // Track the latest controlled value so debounced/queued emits never clobber
  // facet/time changes that landed while the timer was pending.
  const valueRef = useRef(value)
  valueRef.current = value

  // Adopt external q resets (e.g. parent clears the whole filter state).
  useEffect(() => {
    setLocalQ(value.q)
  }, [value.q])

  useEffect(() => () => window.clearTimeout(debounceTimer.current), [])

  /** Immediate emit for non-search changes; flushes any pending q edit too. */
  const emit = (patch: Partial<FilterBarState>): void => {
    window.clearTimeout(debounceTimer.current)
    onChange({ ...valueRef.current, q: localQ, ...patch })
  }

  const handleSearchChange = (q: string): void => {
    setLocalQ(q)
    window.clearTimeout(debounceTimer.current)
    debounceTimer.current = window.setTimeout(() => {
      onChange({ ...valueRef.current, q })
    }, debounceMs)
  }

  const toggleFacetValue = (facetId: string, optionValue: string): void => {
    const current = valueRef.current.facets[facetId] ?? []
    const next = current.includes(optionValue)
      ? current.filter((v) => v !== optionValue)
      : [...current, optionValue]
    const nextFacets = { ...valueRef.current.facets }
    if (next.length > 0) nextFacets[facetId] = next
    else delete nextFacets[facetId]
    emit({ facets: nextFacets })
  }

  const handleOpenChange = (nextOpen: boolean): void => {
    setOpen(nextOpen)
    if (!nextOpen) return
    for (const facet of facets) {
      if (!facet.loadOptions || startedLoads.current.has(facet.id)) continue
      startedLoads.current.add(facet.id)
      setAsyncOptions((s) => ({ ...s, [facet.id]: 'loading' }))
      facet.loadOptions().then(
        (options) => setAsyncOptions((s) => ({ ...s, [facet.id]: options })),
        () => setAsyncOptions((s) => ({ ...s, [facet.id]: 'error' })),
      )
    }
  }

  const facetById = new Map(facets.map((f) => [f.id, f]))
  const optionsFor = (facet: FacetConfig): FacetOption[] | 'loading' | 'error' =>
    facet.options ?? asyncOptions[facet.id] ?? (facet.loadOptions ? 'loading' : [])

  const optionLabel = (facetId: string, optionValue: string): string => {
    const facet = facetById.get(facetId)
    if (!facet) return optionValue
    const opts = optionsFor(facet)
    if (Array.isArray(opts)) {
      const match = opts.find((o) => o.value === optionValue)
      if (match?.label) return match.label
    }
    return optionValue
  }

  const activeEntries = Object.entries(value.facets).filter(([, vals]) => vals.length > 0)
  const activeCount = activeEntries.reduce((acc, [, vals]) => acc + vals.length, 0)

  return (
    <div className={cn(styles.bar, className)}>
      <div className={styles.search}>
        <Search size={13} className={styles.searchIcon} aria-hidden="true" />
        <input
          type="search"
          className={styles.searchInput}
          value={localQ}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      {facets.length > 0 && (
        <Popover.Root open={open} onOpenChange={handleOpenChange}>
          <Popover.Trigger asChild>
            <button type="button" className={styles.filterBtn}>
              <ListFilter size={13} aria-hidden="true" />
              <span>Filter</span>
              {activeCount > 0 && <span className={styles.badge}>{activeCount}</span>}
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content className={styles.popover} align="start" sideOffset={6}>
              {facets.map((facet) => {
                const opts = optionsFor(facet)
                return (
                  <fieldset key={facet.id} className={styles.facetGroup}>
                    <legend className={styles.facetLabel}>{facet.label}</legend>
                    {opts === 'loading' ? (
                      <div className={styles.facetHint}>Loading…</div>
                    ) : opts === 'error' ? (
                      <div className={styles.facetHint}>Failed to load options</div>
                    ) : opts.length === 0 ? (
                      <div className={styles.facetHint}>No options</div>
                    ) : (
                      opts.map((option) => (
                        <label key={option.value} className={styles.option}>
                          <input
                            type="checkbox"
                            className={styles.checkbox}
                            checked={(value.facets[facet.id] ?? []).includes(option.value)}
                            onChange={() => toggleFacetValue(facet.id, option.value)}
                          />
                          <span>{option.label ?? option.value}</span>
                        </label>
                      ))
                    )}
                  </fieldset>
                )
              })}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      )}

      {activeEntries.map(([facetId, vals]) =>
        vals.map((v) => {
          const facetLabel = facetById.get(facetId)?.label ?? facetId
          const valLabel = optionLabel(facetId, v)
          return (
            <span key={`${facetId}:${v}`} className={styles.chip}>
              <span className={styles.chipFacet}>{facetLabel}:</span>
              <span className={styles.chipValue}>{valLabel}</span>
              <button
                type="button"
                className={styles.chipRemove}
                aria-label={`Remove filter ${facetLabel}: ${valLabel}`}
                onClick={() => toggleFacetValue(facetId, v)}
              >
                <X size={11} aria-hidden="true" />
              </button>
            </span>
          )
        }),
      )}

      {activeCount > 0 && (
        <button type="button" className={styles.clearAll} onClick={() => emit({ facets: {} })}>
          Clear all
        </button>
      )}

      <div className={styles.spacer} />

      {showTime && (
        <div className={styles.segmented} role="group" aria-label="Time range">
          {TIME_OPTIONS.map((t) => (
            <button
              key={t.key}
              type="button"
              aria-pressed={value.time === t.key}
              className={cn(styles.segment, value.time === t.key && styles.segmentActive)}
              onClick={() => emit({ time: t.key })}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
      {showTime && value.time === 'custom' && customTimeSlot}

      {end}
    </div>
  )
}
