import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'wouter'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import { Button, Card, ErrorState, LoadingState } from '../components/WorkspaceUI'
import { plannerApi, type Me } from './transport'
import { PlannerAccessContext, usePlannerAccess, type PlannerAccessState } from './access'

// Capability state only: no new authentication, session, login or identity mapping.
// A known ineligible LeadFlow role avoids probing on general pages. It NEVER grants access.
export function PlannerAccessProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [location] = useLocation()
  const [attempt, setAttempt] = useState(0)
  const key = `${user?.id}:${user?.role}:${attempt}`
  const explicit = location === '/distributions' || location === '/planner' || location.startsWith('/planner/')
  const shouldProbe = import.meta.env.VITE_WORKSPACE_ENABLED !== '0' && !!user && (['manager', 'supervisor'].includes(user.role) || explicit)
  const [stored, setStored] = useState<{ key: string; state: PlannerAccessState }>()
  useEffect(() => {
    if (!shouldProbe) return
    const controller = new AbortController()
    plannerApi<Me>('/me', { signal: controller.signal }).then(me => {
      if (me.user.active !== 1 || me.user.role !== user?.role) throw new Error('Сервер вернул данные доступа неожиданного формата.')
      if (!controller.signal.aborted) setStored({ key, state: { status: 'allowed', me } })
    }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 403) {
        const mapping = /соответствия|привязк/i.test(error.message)
        setStored({ key, state: { status: 'denied', message: mapping ? 'Для вашей учётной записи не настроена или отключена привязка к сотруднику. Обратитесь к руководителю.' : 'Раздел «План дня» недоступен для вашей учётной записи. Права LeadFlow не предоставляют доступ к планам автоматически.' } })
      } else {
        const message = error instanceof Error ? error.message : 'Не удалось проверить доступ к плану.'
        const kind = error instanceof ApiError ? 'http' : /формата|JSON/i.test(message) ? 'invalid' : 'network'
        setStored({ key, state: { status: 'error', kind, message, httpStatus: error instanceof ApiError ? error.status : undefined } })
      }
    })
    return () => controller.abort()
  }, [key, shouldProbe, user?.role])
  const state: PlannerAccessState = stored?.key === key ? stored.state : { status: shouldProbe ? 'loading' : 'not_requested' }
  return <PlannerAccessContext.Provider value={{ state, retry: () => setAttempt(value => value + 1) }}>{children}</PlannerAccessContext.Provider>
}

export function PlannerAccessGate({ children, embedded = false }: { children: ReactNode; embedded?: boolean }) {
  const { state, retry } = usePlannerAccess()
  if (state.status === 'allowed') return <>{children}</>
  if (embedded && ['not_requested', 'denied'].includes(state.status)) return null
  if (state.status === 'loading' || state.status === 'not_requested') return <LoadingState text="Проверка доступа к плану…" />
  if (state.status === 'denied') return <Card><h1>План дня недоступен</h1><p className="pw-notice" role="alert">{state.message}</p><Button secondary onClick={retry}>Проверить доступ снова</Button></Card>
  const title = state.kind === 'network' ? 'Нет связи с планировщиком' : state.httpStatus === 503 ? 'Планировщик временно недоступен' : 'Не удалось проверить доступ к плану'
  return <>{!embedded && <h1>План дня</h1>}<ErrorState title={title} message={state.message} retry={retry} retryLabel="Повторить проверку доступа" /></>
}
