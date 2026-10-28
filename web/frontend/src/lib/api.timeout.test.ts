import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('whole-response deadlines and local CSRF', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers() })
  it('times out a stalled JSON body and aborts transport', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockResolvedValue({ status: 200, ok: true, json: () => new Promise(() => {}) })
    vi.stubGlobal('fetch', fetcher)
    const pending = api('/planner/plans')
    const checked = expect(pending).rejects.toThrow('15 секунд')
    await vi.advanceTimersByTimeAsync(15000)
    await checked
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('does not retry a mutation after timeout and explains unknown outcome', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => new Promise(() => {}))
    vi.stubGlobal('fetch', fetcher)
    const checked = expect(api('/planner/plans', { method: 'POST', body: '{}' })).rejects.toThrow('могло сохраниться')
    await vi.advanceTimersByTimeAsync(15000)
    await checked
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('propagates external cancellation without waiting for deadline', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const controller = new AbortController()
    const pending = api('/planner/plans', { signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('rejects invalid JSON clearly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, ok: true, json: () => Promise.reject(new SyntaxError('synthetic')) }))
    await expect(api('/planner/plans')).rejects.toThrow('некорректный JSON')
  })
  it('obtains a session-bound CSRF token only for the explicit local build', async () => {
    vi.stubEnv('VITE_LOCAL_PLANNER_MVP', '1')
    const fetcher = vi.fn().mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ csrf: 'synthetic-csrf-value' }) })
      .mockResolvedValueOnce({ status: 204, ok: true })
    vi.stubGlobal('fetch', fetcher)
    await api('/auth/logout', { method: 'POST' })
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/local/csrf')
    expect(fetcher.mock.calls[1][1].headers['X-CSRF-Token']).toBe('synthetic-csrf-value')
    expect(fetcher.mock.calls[1][1].credentials).toBe('include')
  })
  it('ordinary build obtains CSRF from the server auth boundary',async()=>{
    const fetcher=vi.fn().mockResolvedValueOnce({status:200,ok:true,json:async()=>({csrf:'test-nonce'})}).mockResolvedValueOnce({status:204,ok:true})
    vi.stubGlobal('fetch',fetcher)
    await api('/auth/logout',{method:'POST'})
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/auth/csrf')
    expect(fetcher.mock.calls[1][1].headers['X-CSRF-Token']).toBe('test-nonce')
  })
})
