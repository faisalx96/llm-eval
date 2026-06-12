const JSON_MIME = 'application/json'

/** Error thrown for any non-2xx response, carrying the parsed FastAPI detail. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Backend base URL: the FastAPI root_path injected by the served index.html. */
export function apiBase(): string {
  return (typeof window !== 'undefined' && window.__QYM_ROOT_PATH__) || ''
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  /** JSON-serialized automatically; sets Content-Type: application/json. */
  body?: unknown
  headers?: Record<string, string>
}

/**
 * Tiny typed fetch wrapper:
 * - prefixes paths with window.__QYM_ROOT_PATH__
 * - sends/receives JSON, same-origin credentials
 * - throws ApiError with the parsed `detail` payload on !res.ok
 */
export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { body, headers, ...init } = options

  const res = await fetch(`${apiBase()}${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: {
      Accept: JSON_MIME,
      ...(body !== undefined ? { 'Content-Type': JSON_MIME } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const text = await res.text()
  let parsed: unknown
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!res.ok) {
    const detail =
      parsed !== null && typeof parsed === 'object' && 'detail' in parsed
        ? (parsed as { detail: unknown }).detail
        : parsed
    throw new ApiError(res.status, detail)
  }

  return parsed as T
}
