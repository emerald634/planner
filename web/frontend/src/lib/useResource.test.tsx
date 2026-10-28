import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { useResource } from './useResource'
vi.mock('./api', () => ({ api: vi.fn() }))
const mocked = vi.mocked(api)
describe('independent workspace resources', () => {
  beforeEach(() => vi.resetAllMocks())
  it('ignores late responses after a route change and aborts the old request', async () => {
    let oldResolve!: (value: unknown) => void
    let signal: AbortSignal | null | undefined
    mocked.mockImplementationOnce((_path, options) => { signal = options?.signal; return new Promise(resolve => { oldResolve = resolve }) })
    mocked.mockResolvedValueOnce('new')
    const { result, rerender } = renderHook(({ path }) => useResource<string>(path), { initialProps: { path: '/old' } })
    rerender({ path: '/new' })
    await waitFor(() => expect(result.current.data).toBe('new'))
    expect(signal?.aborted).toBe(true)
    await act(async () => oldResolve('old'))
    expect(result.current.data).toBe('new')
  })
  it('a failed block and its retry do not block or reload a successful block', async () => {
    mocked.mockImplementation(path => path === '/bad' ? Promise.reject(new Error('temporary')) : Promise.resolve(7))
    const { result } = renderHook(() => ({ good: useResource<number>('/good'), bad: useResource<number>('/bad') }))
    await waitFor(() => expect(result.current.bad.error).toBe('temporary'))
    expect(result.current.good.data).toBe(7)
    act(() => result.current.bad.retry())
    await waitFor(() => expect(mocked.mock.calls.filter(([path]) => path === '/bad')).toHaveLength(2))
    expect(mocked.mock.calls.filter(([path]) => path === '/good')).toHaveLength(1)
  })
  it('rejects an invalid payload and can recover with a valid response', async () => {
    const validate = (value: unknown) => typeof value === 'number'
    mocked.mockResolvedValueOnce({ wrong: true }).mockResolvedValueOnce(9)
    const { result } = renderHook(() => useResource<number>('/data', validate))
    await waitFor(() => expect(result.current.error).toContain('неожиданного формата'))
    expect(result.current.data).toBeUndefined()
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.data).toBe(9))
    expect(result.current.error).toBeUndefined()
  })
})
