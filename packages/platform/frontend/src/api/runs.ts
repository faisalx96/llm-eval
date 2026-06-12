/**
 * Typed hooks for the runs surface. Every endpoint below was curl-verified
 * against the live backend (auth mode "none") on 2026-06-12:
 *
 *   GET   /v1/runs?project_slug=…&status=A,B&owner=…&task=…&dataset=…
 *         &model=…&q=…&needs_review=true&sort=-created_at&limit=…&offset=…
 *         → RunListResponse {runs, total, limit, offset}
 *   PATCH /v1/runs/{id}            {display_name}  → {id, name}
 *   POST  /v1/runs/{id}/submit     (owner only; COMPLETED|FAILED|REJECTED)
 *   POST  /v1/runs/{id}/approve    {comment}  (manager/admin; SUBMITTED only)
 *   POST  /v1/runs/{id}/reject     {comment}  (manager/admin; SUBMITTED only)
 *   POST  /api/runs/delete         {file_path: <run_id>} → {ok: true}
 *         (legacy soft-delete — run gets deleted_at; admins can restore via
 *         POST /api/runs/restore, see qym_platform/api/runs.py)
 *   GET   /api/runs/{id}/export-html  (text/html download)
 *   GET   /v1/projects/{id}/overview-stats → ProjectOverviewStats
 *
 * NOTE: /v1/runs has no server-side time-range parameter — the page's time
 * quick-filter is applied client-side on the loaded page.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { toast } from '@/components/ui'
import { apiBase, apiFetch, ApiError } from './client'
import type { components } from './generated'

export type RunSummary = components['schemas']['RunSummary']
export type RunListResponse = components['schemas']['RunListResponse']
export type RunRenameResponse = components['schemas']['RunRenameResponse']
export type ProjectOverviewStats = components['schemas']['ProjectOverviewStats']

/** Poll cadence while any loaded run is still executing. */
export const ACTIVE_POLL_MS = 5_000
/** Background poll cadence when everything on the page is settled. */
export const IDLE_POLL_MS = 30_000

export interface RunListParams {
  projectSlug: string
  /** Workflow statuses — joined into the comma-separated `status` param. */
  statuses?: string[]
  /** Single-value server filters (multi-select is filtered client-side). */
  task?: string
  dataset?: string
  model?: string
  owner?: string
  /** Substring match on run name. */
  q?: string
  /** Only runs awaiting review (SUBMITTED). */
  needsReview?: boolean
  /** created_at | -created_at | duration | -duration. Default -created_at. */
  sort?: string
  limit?: number
  offset?: number
}

/** Build the /v1/runs query string. Exported for tests. */
export function buildRunsQuery(params: RunListParams): string {
  const search = new URLSearchParams()
  search.set('project_slug', params.projectSlug)
  if (params.statuses && params.statuses.length > 0) {
    search.set('status', params.statuses.join(','))
  }
  if (params.task) search.set('task', params.task)
  if (params.dataset) search.set('dataset', params.dataset)
  if (params.model) search.set('model', params.model)
  if (params.owner) search.set('owner', params.owner)
  if (params.q) search.set('q', params.q)
  if (params.needsReview) search.set('needs_review', 'true')
  search.set('sort', params.sort ?? '-created_at')
  search.set('limit', String(params.limit ?? 50))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export const runKeys = {
  all: ['runs'] as const,
  /** Prefix matching every list page for a project (used to invalidate). */
  lists: (projectSlug: string) => ['runs', 'list', projectSlug] as const,
  list: (params: RunListParams) =>
    ['runs', 'list', params.projectSlug, buildRunsQuery(params)] as const,
  needsReviewCount: (projectSlug: string) =>
    ['runs', 'needs-review-count', projectSlug] as const,
  overviewStats: (projectId: string) => ['runs', 'overview-stats', projectId] as const,
}

function hasActiveRuns(data: RunListResponse | undefined): boolean {
  return Boolean(data?.runs.some((r) => r.status === 'RUNNING' || r.status === 'PENDING'))
}

/**
 * Paged run list. Polls every 5s while any loaded run is RUNNING/PENDING,
 * otherwise every 30s. Previous page data is kept while a new page loads.
 */
export function useRunsList(params: RunListParams) {
  return useQuery({
    queryKey: runKeys.list(params),
    queryFn: () => apiFetch<RunListResponse>(`/v1/runs?${buildRunsQuery(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      hasActiveRuns(query.state.data) ? ACTIVE_POLL_MS : IDLE_POLL_MS,
  })
}

/** Cheap count of runs awaiting review: needs_review=true&limit=1 → total. */
export function useNeedsReviewCount(projectSlug: string) {
  return useQuery({
    queryKey: runKeys.needsReviewCount(projectSlug),
    queryFn: () =>
      apiFetch<RunListResponse>(
        `/v1/runs?${buildRunsQuery({ projectSlug, needsReview: true, limit: 1 })}`,
      ),
    select: (data) => data.total,
    refetchInterval: IDLE_POLL_MS,
  })
}

/** Project stat chips: total runs / models / status mix. */
export function useProjectOverviewStats(projectId: string | undefined) {
  return useQuery({
    queryKey: runKeys.overviewStats(projectId ?? ''),
    queryFn: () =>
      apiFetch<ProjectOverviewStats>(`/v1/projects/${projectId}/overview-stats`),
    enabled: projectId != null && projectId !== '',
    refetchInterval: IDLE_POLL_MS,
  })
}

/** Offline HTML export URL for a run (plain navigation, not JSON). */
export function exportHtmlUrl(runId: string): string {
  return `${apiBase()}/api/runs/${runId}/export-html`
}

function errorDescription(error: unknown): string | undefined {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error && error.message) return error.message
  return undefined
}

/** Invalidate everything a run mutation can affect for a project. */
function invalidateRunData(
  queryClient: ReturnType<typeof useQueryClient>,
  projectSlug: string,
): void {
  void queryClient.invalidateQueries({ queryKey: runKeys.lists(projectSlug) })
  void queryClient.invalidateQueries({ queryKey: runKeys.needsReviewCount(projectSlug) })
  void queryClient.invalidateQueries({ queryKey: ['runs', 'overview-stats'] })
}

export interface RenameRunVars {
  runId: string
  displayName: string
}

type ListSnapshot = Array<[readonly unknown[], RunListResponse | undefined]>

/**
 * PATCH /v1/runs/{id} {display_name}. Optimistic: every cached list page for
 * the project is patched immediately; on error the snapshot is restored and
 * an error toast is raised.
 */
export function useRenameRun(projectSlug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, displayName }: RenameRunVars) =>
      apiFetch<RunRenameResponse>(`/v1/runs/${runId}`, {
        method: 'PATCH',
        body: { display_name: displayName },
      }),
    onMutate: async ({ runId, displayName }) => {
      await queryClient.cancelQueries({ queryKey: runKeys.lists(projectSlug) })
      const snapshot: ListSnapshot = queryClient.getQueriesData<RunListResponse>({
        queryKey: runKeys.lists(projectSlug),
      })
      queryClient.setQueriesData<RunListResponse>(
        { queryKey: runKeys.lists(projectSlug) },
        (old) =>
          old
            ? {
                ...old,
                runs: old.runs.map((run) =>
                  run.id === runId ? { ...run, name: displayName } : run,
                ),
              }
            : old,
      )
      return { snapshot }
    },
    onError: (error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, data)
      }
      toast({
        variant: 'error',
        title: 'Rename failed',
        description: errorDescription(error),
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: runKeys.lists(projectSlug) })
    },
  })
}

/** POST /v1/runs/{id}/submit — owner submits a finished run for review. */
export function useSubmitRun(projectSlug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) =>
      apiFetch<{ ok: boolean; status: string }>(`/v1/runs/${runId}/submit`, {
        method: 'POST',
        body: {},
      }),
    onSuccess: () => {
      toast({ variant: 'success', title: 'Submitted for review' })
    },
    onError: (error) => {
      toast({
        variant: 'error',
        title: 'Submit failed',
        description: errorDescription(error),
      })
    },
    onSettled: () => invalidateRunData(queryClient, projectSlug),
  })
}

export interface DecisionVars {
  runId: string
  comment: string
}

/** POST /v1/runs/{id}/approve {comment} — manager/admin approves a SUBMITTED run. */
export function useApproveRun(projectSlug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, comment }: DecisionVars) =>
      apiFetch<{ ok: boolean; status: string }>(`/v1/runs/${runId}/approve`, {
        method: 'POST',
        body: { comment },
      }),
    onSuccess: () => {
      toast({ variant: 'success', title: 'Run approved' })
    },
    onError: (error) => {
      toast({
        variant: 'error',
        title: 'Approve failed',
        description: errorDescription(error),
      })
    },
    onSettled: () => invalidateRunData(queryClient, projectSlug),
  })
}

/** POST /v1/runs/{id}/reject {comment} — manager/admin rejects a SUBMITTED run. */
export function useRejectRun(projectSlug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, comment }: DecisionVars) =>
      apiFetch<{ ok: boolean; status: string }>(`/v1/runs/${runId}/reject`, {
        method: 'POST',
        body: { comment },
      }),
    onSuccess: () => {
      toast({ variant: 'success', title: 'Run rejected' })
    },
    onError: (error) => {
      toast({
        variant: 'error',
        title: 'Reject failed',
        description: errorDescription(error),
      })
    },
    onSettled: () => invalidateRunData(queryClient, projectSlug),
  })
}

/**
 * Soft-delete one or more runs via the legacy endpoint
 * POST /api/runs/delete {file_path: <run_id>} (one call per run — the
 * endpoint takes a single id). Admins can restore deleted runs later.
 */
export function useDeleteRuns(projectSlug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runIds: string[]) => {
      for (const runId of runIds) {
        await apiFetch<{ ok: boolean }>('/api/runs/delete', {
          method: 'POST',
          body: { file_path: runId },
        })
      }
      return runIds.length
    },
    onSuccess: (deleted) => {
      toast({
        variant: 'success',
        title: `Moved ${deleted === 1 ? 'run' : `${deleted} runs`} to Deleted Runs`,
        description: 'Admins can restore it later.',
      })
    },
    onError: (error) => {
      toast({
        variant: 'error',
        title: 'Delete failed',
        description: errorDescription(error),
      })
    },
    onSettled: () => invalidateRunData(queryClient, projectSlug),
  })
}
