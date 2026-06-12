import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiBase, apiFetch } from './client'

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete window.__QYM_ROOT_PATH__
  })

  it('prefixes requests with window.__QYM_ROOT_PATH__ and parses JSON', async () => {
    window.__QYM_ROOT_PATH__ = '/qym'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiFetch<{ ok: boolean }>('/api/projects')

    expect(apiBase()).toBe('/qym')
    expect(result).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/qym/api/projects')
  })

  it('throws ApiError carrying the parsed detail on non-2xx responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'forbidden by origin guard' }), { status: 403 }),
      ),
    )

    const err = await apiFetch('/api/projects', { method: 'POST', body: { name: 'x' } }).then(
      () => {
        throw new Error('expected apiFetch to reject')
      },
      (e: unknown) => e,
    )

    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 403, detail: 'forbidden by origin guard' })
  })
})
