/** Data-display components: tables, filters, pagination, metrics, code. */

export {
  DataTable,
  createSelectionColumn,
  computeZeroEntropyColumns,
  VIRTUALIZE_THRESHOLD,
} from './DataTable'
export type {
  DataTableProps,
  DataTableColumn,
  DataColumnMeta,
  ColumnDef,
  Row,
  RowSelectionState,
  SortingState,
  VisibilityState,
  OnChangeFn,
} from './DataTable'

export { FilterBar, EMPTY_FILTER_STATE } from './FilterBar'
export type {
  FilterBarProps,
  FilterBarState,
  FacetConfig,
  FacetOption,
  TimeKey,
} from './FilterBar'

export { Pagination } from './Pagination'
export type { PaginationProps } from './Pagination'

export { MetricDelta, formatMetric } from './MetricDelta'
export type { MetricDeltaProps, MetricFormat } from './MetricDelta'

export { CodePanel } from './CodePanel'
export type { CodePanelProps, CodePanelTone } from './CodePanel'

export { JsonView } from './JsonView'
export type { JsonViewProps } from './JsonView'

export { diffWords } from './diff'
export type { DiffSegment, DiffType } from './diff'

export { StatCard } from './StatCard'
export type { StatCardProps } from './StatCard'
