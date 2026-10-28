import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { AuthProvider, useAuth } from './AuthContext'

vi.mock('../lib/api', () => ({ api: vi.fn() }))

const mockedApi = vi.mocked(api)

const fakeUser = {
  id: 1,
  email: 'admin@example.com',
  full_name: 'Admin',
  role: 'admin' as const,
  is_active: true,
  telegram_chat_id: null,
  bitrix_user_id: null,
  work_days: [0, 1, 2, 3, 4],
  workday_start: '09:00',
  workday_end: '18:00',
  unavailable_until: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function Probe() {
  const { user, loading, login, logout } = useAuth()
  if (loading) return <div>loading</div>
  return (
    <div>
      <div>{user ? `logged in as ${user.email}` : 'anonymous'}</div>
      <button onClick={() => login('admin@example.com', 'password')}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  )
}

describe('AuthProvider', () => {
  afterEach(() => {
    mockedApi.mockReset()
    vi.useRealTimers()
  })

  it('restores the session from the httpOnly cookie via /auth/me on mount', async () => {
    mockedApi.mockResolvedValueOnce(fakeUser)
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('logged in as admin@example.com')).toBeInTheDocument())
    expect(mockedApi).toHaveBeenCalledWith('/auth/me')
  })

  it('shows anonymous when there is no valid session', async () => {
    mockedApi.mockRejectedValueOnce(new Error('401'))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('anonymous')).toBeInTheDocument())
  })

  it('login stores the user returned by the backend without a second round-trip', async () => {
    mockedApi.mockRejectedValueOnce(new Error('401'))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('anonymous')).toBeInTheDocument())

    mockedApi.mockResolvedValueOnce(fakeUser)
    await userEvent.click(screen.getByText('login'))

    await waitFor(() => expect(screen.getByText('logged in as admin@example.com')).toBeInTheDocument())
    expect(mockedApi).toHaveBeenLastCalledWith(
      '/auth/login',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('failed logout blocks protected UI and allows retry without claiming revoke', async () => {
    mockedApi.mockResolvedValueOnce(fakeUser)
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('logged in as admin@example.com')).toBeInTheDocument())

    mockedApi.mockRejectedValueOnce(new Error('network error'))
    await userEvent.click(screen.getByText('logout'))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.queryByText('anonymous')).not.toBeInTheDocument()
    expect(screen.queryByText('logged in as admin@example.com')).not.toBeInTheDocument()
    mockedApi.mockResolvedValueOnce(undefined)
    await userEvent.click(screen.getByText('Повторить выход'))
    await waitFor(() => expect(screen.getByText('anonymous')).toBeInTheDocument())
  })

  it('confirmed logout clears user state', async () => {
    mockedApi.mockResolvedValueOnce(fakeUser)
    render(<AuthProvider><Probe /></AuthProvider>)
    await screen.findByText('logged in as admin@example.com')
    mockedApi.mockResolvedValueOnce(undefined)
    await userEvent.click(screen.getByText('logout'))
    await screen.findByText('anonymous')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a stalled logout times out, aborts and offers retry', async () => {
    mockedApi.mockResolvedValueOnce(fakeUser)
    render(<AuthProvider><Probe /></AuthProvider>)
    await screen.findByText('logged in as admin@example.com')
    mockedApi.mockImplementationOnce(() => new Promise(() => {}))
    vi.useFakeTimers()
    fireEvent.click(screen.getByText('logout'))
    expect(screen.getByRole('status')).toHaveTextContent('Выполняется выход')
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(mockedApi.mock.calls.at(-1)?.[1]?.signal?.aborted).toBe(true)
    expect(screen.queryByText('anonymous')).not.toBeInTheDocument()
  })
})
