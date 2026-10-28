const API_URL = import.meta.env.VITE_API_URL || '/api/v1'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

// FastAPI отдаёт detail либо строкой (HTTPException), либо массивом объектов
// ошибок валидации Pydantic ([{loc, msg, ...}]) при 422 — приводим к строке.
function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== 'body') : []
      const field = loc.join('.')
      const msg = typeof item?.msg === 'string' ? item.msg : 'Некорректное значение'
      return field ? `${field}: ${msg}` : msg
    })
    return messages.join('; ') || 'Ошибка запроса'
  }
  return 'Ошибка запроса'
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const mutation = options.method && !['GET', 'HEAD'].includes(options.method)
  let timer: ReturnType<typeof setTimeout> | undefined
  let rejectAbort: (reason: Error) => void = () => {}
  const abort = () => { controller.abort(); rejectAbort(new DOMException('Загрузка отменена', 'AbortError')) }
  options.signal?.addEventListener('abort', abort, { once: true })
  try {
    if (options.signal?.aborted) throw new DOMException('Загрузка отменена', 'AbortError')
    return await Promise.race([
      new Promise<never>((_, reject) => {
        rejectAbort = reject
        timer = setTimeout(() => {
          controller.abort()
          reject(new Error(mutation ? 'Сервер не ответил за 15 секунд. Изменение могло сохраниться: сначала обновите данные.' : 'Сервер не ответил за 15 секунд. Повторите загрузку.'))
        }, 15000)
      }),
      (async () => {
  let csrf: string | undefined
  if (mutation) {
    const bootstrap = await fetch(`${API_URL}${import.meta.env.VITE_LOCAL_PLANNER_MVP === '1' ? '/local/csrf' : '/auth/csrf'}`, { credentials: 'include', signal: controller.signal, cache: 'no-store' })
    if (!bootstrap.ok) throw new ApiError(bootstrap.status, 'Не удалось проверить безопасность запроса')
    let value: unknown
    try { value = await bootstrap.json() }
    catch (error) { throw new Error('Некорректный ответ проверки безопасности', { cause: error }) }
    if (!value || typeof value !== 'object' || !('csrf' in value) || typeof value.csrf !== 'string') throw new Error('Некорректный ответ проверки безопасности')
    csrf = value.csrf
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    signal: controller.signal,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    },
  })
  if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
    window.location.href = '/login'
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, formatDetail(payload?.detail))
  }
  if (response.status === 204) return undefined as T
  try { return await response.json() as T }
  catch { throw new Error('Сервер вернул некорректный JSON. Обновите данные.') }
      })(),
    ])
  } catch (error) {
    if (error instanceof TypeError) throw new Error(mutation ? 'Нет связи с сервером. Изменение могло сохраниться: сначала обновите данные.' : 'Нет связи с сервером. Проверьте соединение и повторите загрузку.', { cause: error })
    throw error
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', abort)
  }
}

