import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiBase, apiFetch } from '@/api/client'
import type { components } from '@/api/generated'

/**
 * Typed hooks for the run-detail surface.
 *
 * Endpoints (all curl-verified against the live backend on 2026-06-12):
 *   GET   /v1/runs/{id}                      → RunDetail
 *   GET   /v1/runs/{id}/items                → RunItemsResponse (paged, limit ≤ 100)
 *   GET   /v1/runs/{id}/items/{item_id}      → RunItemDetail
 *   PATCH /v1/runs/{id}                      → rename (optimistic)
 *   POST  /v1/runs/{id}/submit|approve|reject
 *   POST  /api/runs/delete  {file_path: run_id}   (legacy soft delete)
 *   POST  /api/runs/{id}/analyze                  (400 when no LLM connection)
 *   GET   /api/corrections?project_slug=…         (per-item correction records)
 *   POST  /api/corrections/{id}/approve|reject
 */

export type RunDetail = components['schemas']['RunDetail']
export type RunSummary = components['schemas']['RunSummary']
export type RunListResponse = components['schemas']['RunListResponse']
export type RunItemSlim = components['schemas']['RunItemSlim']
export type RunItemsResponse = components['schemas']['RunItemsResponse']
export type RunItemDetail = components['schemas']['RunItemDetail']
export type MetricStats = components['schemas']['MetricStats']
export type ApprovalContext = components['schemas']['ApprovalContext']

/** Items are paged at 100/request; we assemble pages client-side up to this
 *  cap so sorting/filtering stays fluid in the browser. Runs above the cap
 *  fall back to server-side filters (see useRunItems callers). */
export const ITEMS_PAGE_SIZE = 100
export const CLIENT_ITEMS_CAP = 500

/** Poll cadence while a run is RUNNING. */
export const RUNNING_POLL_MS = 4000

export const runDetailKeys = {
  detail: (runId: string) => ['run-detail', runId] as const,
  items: (runId: string, params: RunItemsParams) => ['run-items', runId, params] as const,
  item: (runId: string, itemId: string) => ['run-item', runId, itemId] as const,
  siblings: (runId: string) => ['run-siblings', runId] as const,
  corrections: (runId: string) => ['run-corrections', runId] as const,
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const out = search.toString()
  return out ? `?${out}` : ''
}

/* ── Run detail ────────────────────────────────────────────────────────── */

export function useRunDetail(runId: string) {
  return useQuery({
    queryKey: runDetailKeys.detail(runId),
    queryFn: () => apiFetch<RunDetail>(`/v1/runs/${runId}`),
    enabled: Boolean(runId),
    // Live progress while the run executes.
    refetchInterval: (query) =>
      query.state.data?.status === 'RUNNING' ? RUNNING_POLL_MS : false,
  })
}

/* ── Items (fetch-all-pages with cap) ──────────────────────────────────── */

/** Server-side query params supported by GET /v1/runs/{id}/items. */
export interface RunItemsParams {
  q?: string
  failed_only?: boolean
  metric?: string
  below?: number
  /** index | latency | -latency | score */
  sort?: string
}

export interface RunItemsAll {
  items: RunItemSlim[]
  total: number
  /** True when total > CLIENT_ITEMS_CAP and only the first cap was loaded. */
  truncated: boolean
}

async function fetchAllItems(runId: string, params: RunItemsParams): Promise<RunItemsAll> {
  const items: RunItemSlim[] = []
  let total = 0
  for (let offset = 0; ; offset += ITEMS_PAGE_SIZE) {
    const page = await apiFetch<RunItemsResponse>(
      `/v1/runs/${runId}/items${qs({ ...params, limit: ITEMS_PAGE_SIZE, offset })}`,
    )
    total = page.total
    items.push(...page.items)
    if (page.items.length === 0 || items.length >= total || items.length >= CLIENT_ITEMS_CAP) {
      break
    }
  }
  return { items, total, truncated: items.length < total }
}

/**
 * All items for a run (assembled from 100-row pages, capped at
 * CLIENT_ITEMS_CAP). For runs at/below the cap callers do filtering and
 * sorting client-side and only `q` is sent to the server; above the cap
 * the caller passes its filters through `params` for server evaluation.
 */
export function useRunItems(runId: string, params: RunItemsParams, options?: { poll?: boolean }) {
  return useQuery({
    queryKey: runDetailKeys.items(runId, params),
    queryFn: () => fetchAllItems(runId, params),
    enabled: Boolean(runId),
    placeholderData: (previous) => previous,
    refetchInterval: options?.poll ? RUNNING_POLL_MS : false,
  })
}

export function useRunItemDetail(runId: string, itemId: string, enabled = true) {
  return useQuery({
    queryKey: runDetailKeys.item(runId, itemId),
    queryFn: () =>
      apiFetch<RunItemDetail>(`/v1/runs/${runId}/items/${encodeURIComponent(itemId)}`),
    enabled: Boolean(runId && itemId) && enabled,
  })
}

/**
 * Full detail for every item (for the category-performance aggregation).
 * Only allowed up to CLIENT_ITEMS_CAP ids; fetched lazily (enabled when the
 * analysis section is opened) in chunks of 8 concurrent requests.
 */
export function useAllItemDetails(runId: string, itemIds: string[], enabled: boolean) {
  return useQuery({
    queryKey: ['run-item-details-all', runId, itemIds.length],
    enabled: enabled && itemIds.length > 0 && itemIds.length <= CLIENT_ITEMS_CAP,
    staleTime: 60_000,
    queryFn: async () => {
      const out: RunItemDetail[] = []
      const CHUNK = 8
      for (let i = 0; i < itemIds.length; i += CHUNK) {
        const chunk = itemIds.slice(i, i + CHUNK)
        const results = await Promise.all(
          chunk.map((id) =>
            apiFetch<RunItemDetail>(`/v1/runs/${runId}/items/${encodeURIComponent(id)}`),
          ),
        )
        out.push(...results)
      }
      return out
    },
  })
}

/* ── Siblings (for "Compare vs previous") ──────────────────────────────── */

/**
 * Runs sharing this run's task/dataset/model in the same project — the
 * candidate pool for "Compare vs previous". Filtering down to the actual
 * previous run (same group_key, earlier started_at, finished) happens
 * client-side in features/run-detail/lib.ts.
 */
export function useRunSiblings(projectSlug: string, run: RunDetail | undefined) {
  return useQuery({
    queryKey: runDetailKeys.siblings(run?.id ?? ''),
    queryFn: () =>
      apiFetch<RunListResponse>(
        `/v1/runs${qs({
          project_slug: projectSlug,
          task: run?.task,
          dataset: run?.dataset,
          model: run?.model ?? undefined,
          limit: 100,
        })}`,
      ),
    enabled: Boolean(projectSlug && run),
    select: (data) => data.runs,
  })
}

/* ── Mutations ─────────────────────────────────────────────────────────── */

/** Rename (PATCH /v1/runs/{id}) with an optimistic cache update. */
export function useRenameRun(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (displayName: string) =>
      apiFetch<{ id: string; name: string }>(`/v1/runs/${runId}`, {
        method: 'PATCH',
        body: { display_name: displayName },
      }),
    onMutate: async (displayName) => {
      await queryClient.cancelQueries({ queryKey: runDetailKeys.detail(runId) })
      const previous = queryClient.getQueryData<RunDetail>(runDetailKeys.detail(runId))
      if (previous) {
        queryClient.setQueryData<RunDetail>(runDetailKeys.detail(runId), {
          ...previous,
          name: displayName,
        })
      }
      return { previous }
    },
    onError: (_err, _name, context) => {
      if (context?.previous) {
        queryClient.setQueryData(runDetailKeys.detail(runId), context.previous)
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: runDetailKeys.detail(runId) })
    },
  })
}

function useRunAction(runId: string, path: string, withComment: boolean) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (comment?: string) =>
      apiFetch<{ ok: boolean; status: string }>(`/v1/runs/${runId}/${path}`, {
        method: 'POST',
        body: withComment ? { comment: comment ?? '' } : undefined,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runDetailKeys.detail(runId) })
    },
  })
}

export function useSubmitRun(runId: string) {
  return useRunAction(runId, 'submit', false)
}

export function useApproveRun(runId: string) {
  return useRunAction(runId, 'approve', true)
}

export function useRejectRun(runId: string) {
  return useRunAction(runId, 'reject', true)
}

/** Soft delete (legacy endpoint expects the run id as `file_path`). */
export function useDeleteRun() {
  return useMutation({
    mutationFn: (runId: string) =>
      apiFetch<{ ok: boolean }>('/api/runs/delete', {
        method: 'POST',
        body: { file_path: runId },
      }),
  })
}

/** POST /api/runs/{id}/analyze — 400 with a helpful detail when the project
 *  has no LLM connection; callers surface ApiError.detail in a toast. */
export function useAnalyzeRun(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<Record<string, unknown>>(`/api/runs/${runId}/analyze`, {
        method: 'POST',
        body: {},
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['run-items', runId] })
      void queryClient.invalidateQueries({ queryKey: runDetailKeys.corrections(runId) })
    },
  })
}

/* ── Corrections (review queue records per item) ───────────────────────── */

/** Subset of the /api/corrections record the run-detail UI needs. */
export interface CorrectionEntry {
  id: number
  run_id: string
  item_id: string
  status: string
  human_root_cause: string
  human_root_cause_detail: string
  human_solution: string
  ai_root_cause: string
  ai_root_cause_detail: string
  ai_solution: string
  is_active: boolean
}

interface CorrectionsResponse {
  corrections: CorrectionEntry[]
}

/**
 * Correction records for this run keyed by item_id. The legacy corrections
 * list has no run_id filter, so we fetch the project's records and narrow
 * client-side (≤500 records server-capped).
 */
export function useRunCorrections(projectSlug: string, runId: string) {
  return useQuery({
    queryKey: runDetailKeys.corrections(runId),
    queryFn: () =>
      apiFetch<CorrectionsResponse>(`/api/corrections${qs({ project_slug: projectSlug, limit: 500 })}`),
    enabled: Boolean(projectSlug && runId),
    select: (data) => {
      const byItem = new Map<string, CorrectionEntry>()
      for (const entry of data.corrections) {
        if (entry.run_id === runId && entry.is_active) byItem.set(entry.item_id, entry)
      }
      return byItem
    },
  })
}

/** Approve/reject one correction record (both routes exist server-side). */
export function useCorrectionDecision(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ correctionId, action }: { correctionId: number; action: 'approve' | 'reject' }) =>
      apiFetch<CorrectionEntry>(`/api/corrections/${correctionId}/${action}`, {
        method: 'POST',
        body: { comment: '' },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runDetailKeys.corrections(runId) })
      void queryClient.invalidateQueries({ queryKey: ['run-items', runId] })
    },
  })
}

/* ── Export URLs ───────────────────────────────────────────────────────── */

export function exportHtmlUrl(runId: string): string {
  return `${apiBase()}/api/runs/${runId}/export-html`
}

export function docsUrl(): string {
  return `${apiBase()}/docs/`
}
