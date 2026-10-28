import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

function mockFetchOnce(response: { status: number; body?: unknown }) {
  const fetchMock = vi.fn((url: string, options: RequestInit) => { void options; return Promise.resolve(url.endsWith('/auth/csrf') ? { ok: true, status: 200, json: async () => ({ csrf: 'synthetic-csrf' }) } : {
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    json: async () => response.body,
  }) })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends credentials so the httpOnly session cookie is included', async () => {
    const fetchMock = mockFetchOnce({ status: 200, body: { ok: true } })
    await api('/leads')
    const [, options] = fetchMock.mock.calls[0]
    expect(options.credentials).toBe('include')
  })

  it('returns parsed JSON on success', async () => {
    mockFetchOnce({ status: 200, body: { id: 1 } })
    await expect(api('/leads/1')).resolves.toEqual({ id: 1 })
  })

  it('returns undefined for 204 responses', async () => {
    mockFetchOnce({ status: 204 })
    await expect(api('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('throws ApiError with the string detail from a plain HTTPException', async () => {
    mockFetchOnce({ status: 404, body: { detail: 'Лид не найден' } })
    await expect(api('/leads/999')).rejects.toMatchObject(
      new ApiError(404, 'Лид не найден'),
    )
  })

  it('formats a Pydantic validation error array into a readable string', async () => {
    mockFetchOnce({
      status: 422,
      body: { detail: [{ loc: ['body', 'source'], msg: 'Field required' }] },
    })
    await expect(api('/leads', { method: 'POST' })).rejects.toMatchObject(
      new ApiError(422, 'source: Field required'),
    )
  })
})

describe('api unauthenticated redirect', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'location', { value: { href: '' }, writable: true })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('redirects to /login on 401 for a regular request', async () => {
    mockFetchOnce({ status: 401, body: { detail: 'Требуется авторизация' } })
    await expect(api('/leads')).rejects.toBeInstanceOf(ApiError)
    expect(window.location.href).toBe('/login')
  })

  it('does not redirect on 401 from the initial /auth/me check', async () => {
    mockFetchOnce({ status: 401, body: { detail: 'Требуется авторизация' } })
    await expect(api('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(window.location.href).toBe('')
  })
})
