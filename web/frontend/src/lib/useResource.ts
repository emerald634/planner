import { useEffect, useState } from 'react'
import { api } from './api'

// Each block owns its errors/retry. Stale responses and unmounted pages are ignored.
export function useResource<T>(path: string, validate?: (value: unknown) => boolean) {
  const [attempt, setAttempt] = useState(0)
  const key = `${path}:${attempt}`
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>()
  useEffect(() => {
    const controller = new AbortController()
    api<T>(path, { signal: controller.signal }).then(data => {
      if (validate && !validate(data)) throw new Error('Сервер вернул данные неожиданного формата.')
      if (!controller.signal.aborted) setState({ key, data })
    }).catch(error => {
      if (!controller.signal.aborted) setState({ key, error: error instanceof Error ? error.message : 'Не удалось загрузить данные.' })
    })
    return () => controller.abort()
  }, [path, key, validate])
  const current = state?.key === key ? state : undefined
  return { data: current?.data, error: current?.error, loading: !current, retry: () => setAttempt(value => value + 1) }
}
