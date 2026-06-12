import { cn } from '@/lib/cn'
import styles from './Pagination.module.css'

/**
 * The one pagination dialect: ‹ Prev · Page N of M · Next › plus an optional
 * page-size select and "Showing X–Y of Z". Fully controlled; `page` is 1-based.
 */

export interface PaginationProps {
  /** Current page, 1-based. */
  page: number
  /** Total number of pages. */
  pageCount: number
  onPageChange: (page: number) => void
  /** Enables the page-size select when paired with onPageSizeChange. */
  pageSize?: number
  onPageSizeChange?: (size: number) => void
  pageSizeOptions?: number[]
  /** Enables "Showing X–Y of Z" (needs pageSize too). */
  totalItems?: number
  className?: string
}

const DEFAULT_SIZES = [25, 50, 100]

export function Pagination({
  page,
  pageCount,
  onPageChange,
  pageSize,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_SIZES,
  totalItems,
  className,
}: PaginationProps) {
  const safePageCount = Math.max(1, pageCount)
  const showRange = totalItems != null && pageSize != null
  const from = showRange ? (totalItems === 0 ? 0 : (page - 1) * pageSize + 1) : 0
  const to = showRange ? Math.min(page * pageSize, totalItems) : 0

  return (
    <nav className={cn(styles.root, className)} aria-label="Pagination">
      {showRange && (
        <span className={styles.showing}>
          Showing{' '}
          <span className={styles.num}>
            {from}–{to}
          </span>{' '}
          of <span className={styles.num}>{totalItems}</span>
        </span>
      )}

      <div className={styles.pager}>
        <button
          type="button"
          className={styles.navBtn}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          ‹ Prev
        </button>
        <span className={styles.dot} aria-hidden="true">
          ·
        </span>
        <span className={styles.pageInfo}>
          Page <span className={styles.num}>{page}</span> of{' '}
          <span className={styles.num}>{safePageCount}</span>
        </span>
        <span className={styles.dot} aria-hidden="true">
          ·
        </span>
        <button
          type="button"
          className={styles.navBtn}
          disabled={page >= safePageCount}
          onClick={() => onPageChange(page + 1)}
        >
          Next ›
        </button>
      </div>

      {pageSize != null && onPageSizeChange && (
        <label className={styles.sizeLabel}>
          <span>Rows</span>
          <select
            className={styles.sizeSelect}
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            aria-label="Rows per page"
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      )}
    </nav>
  )
}
