import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import type { User } from '../types'
import { plannerApi, type Me } from './transport'
import { PlannerAccessGate, PlannerAccessProvider } from './PlannerAccess'
import { usePlannerAccess } from './access'
vi.mock('../auth/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('./transport', () => ({ plannerApi: vi.fn() }))
const request = vi.mocked(plannerApi)
function user(role: User['role'], id = 101) {
  vi.mocked(useAuth).mockReturnValue({ user: { id, role } as User, loading: false, login: vi.fn(), logout: vi.fn() })
}
function me(role: 'manager' | 'supervisor' = 'manager'): Me {
  return { user: { id: role === 'manager' ? 1 : 3, role, active: 1, name: 'Искусственный сотрудник' }, today: '2026-10-27', timezone: 'Europe/Moscow', crm: { connected: false, message: 'Нет данных' } }
}
function State() {
  const { state } = usePlannerAccess()
  return <output data-testid="state">{state.status}{state.status === 'allowed' ? `:${state.me.user.id}` : ''}</output>
}
function View({ embedded = false }: { embedded?: boolean }) {
  return <PlannerAccessProvider><State /><PlannerAccessGate embedded={embedded}><div data-testid="private">private plans</div></PlannerAccessGate></PlannerAccessProvider>
}
describe('one shared Planner capability state', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.stubEnv('VITE_LOCAL_PLANNER_MVP', '1'); window.history.replaceState(null, '', '/'); user('manager') })
  afterEach(() => vi.unstubAllEnvs())
  it('admin general pages never probe or mount Planner', async () => {
    user('admin'); render(<View embedded />)
    for (const path of ['/statistics', '/managers', '/leads']) await act(async () => { window.history.pushState(null, '', path) })
    expect(request).not.toHaveBeenCalled(); expect(screen.queryByTestId('private')).toBeNull()
    expect(screen.getByTestId('state')).toHaveTextContent('not_requested')
  })
  it('does not allow a manager while server identity is pending', async () => {
    let resolve!: (value: Me) => void
    request.mockImplementation(() => new Promise<Me>(done => { resolve = done }))
    window.history.replaceState(null, '', '/planner?employee=999')
    render(<View />)
    expect(screen.queryByTestId('private')).toBeNull()
    expect(screen.getByTestId('state')).toHaveTextContent('loading')
    await act(async () => resolve(me()))
    expect(screen.getByTestId('state')).toHaveTextContent('allowed:1')
    expect(screen.getByTestId('private')).toBeVisible(); expect(request).toHaveBeenCalledTimes(1)
  })
  it('uses verified supervisor identity', async () => {
    user('supervisor'); request.mockResolvedValue(me('supervisor')); render(<View />)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('allowed:3'))
  })
  it('an explicit admin URL obtains a real denial instead of granting supervisor', async () => {
    user('admin'); window.history.replaceState(null, '', '/planner')
    request.mockRejectedValue(new ApiError(403, 'Права отдельно не назначены.')); render(<View />)
    await screen.findByRole('heading', { name: 'План дня недоступен' })
    expect(request).toHaveBeenCalledTimes(1); expect(screen.queryByTestId('private')).toBeNull()
  })
  it('keeps unmapped denial silent on general pages and explains an explicit access', async () => {
    request.mockRejectedValue(new ApiError(403, 'Нет подтверждённого соответствия сотрудника.'))
    const { rerender } = render(<View embedded />)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('denied'))
    expect(screen.queryByRole('alert')).toBeNull()
    await act(async () => { window.history.pushState(null, '', '/planner/tasks') }); rerender(<View />)
    expect(screen.getByRole('alert')).toHaveTextContent('не настроена или отключена привязка')
    expect(screen.queryByTestId('private')).toBeNull(); expect(request).toHaveBeenCalledTimes(1)
  })
  it('503 is temporary and retry can recover using the real identity path', async () => {
    request.mockRejectedValueOnce(new ApiError(503, 'Временный отказ')).mockResolvedValueOnce(me())
    render(<View />); await screen.findByText('Планировщик временно недоступен')
    expect(screen.queryByText('План дня недоступен')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку доступа' }))
    await screen.findByTestId('private'); expect(request).toHaveBeenCalledTimes(2)
  })
  it('network failure is not a permission denial', async () => {
    request.mockRejectedValue(new Error('Нет связи с сервером.'))
    render(<View />); await screen.findByText('Нет связи с планировщиком')
    expect(screen.getByTestId('state')).toHaveTextContent('error'); expect(screen.queryByTestId('private')).toBeNull()
  })
  it('ignores an aborted identity response after account change', async () => {
    let resolve!: (value: Me) => void
    request.mockImplementationOnce(() => new Promise<Me>(done => { resolve = done })).mockResolvedValueOnce(me('supervisor'))
    const { rerender } = render(<View />)
    const signal = request.mock.calls[0][1]?.signal
    user('supervisor', 201); rerender(<View />)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('allowed:3'))
    expect(signal?.aborted).toBe(true)
    await act(async () => resolve(me()))
    expect(screen.getByTestId('state')).toHaveTextContent('allowed:3')
  })
  it('a mismatched role response is invalid data and cannot grant access', async () => {
    request.mockResolvedValue(me('supervisor')); render(<View />)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('error'))
    expect(screen.queryByTestId('private')).toBeNull()
  })
  it('a disabled MVP never probes Planner', () => {
    vi.stubEnv('VITE_WORKSPACE_ENABLED', '0'); render(<View embedded />)
    expect(request).not.toHaveBeenCalled(); expect(screen.queryByTestId('private')).toBeNull()
  })
})
