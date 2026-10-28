import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { User } from '../types'

interface AuthValue {
  user: User | null
  loading: boolean
  login(email: string, password: string): Promise<void>
  logout(): Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [logoutState, setLogoutState] = useState<'idle' | 'pending' | 'error'>('idle')

  // Сессия хранится в httpOnly-куке, JS её не видит — единственный способ
  // узнать, залогинен ли пользователь, это спросить бэкенд.
  useEffect(() => {
    api<User>('/auth/me').then(setUser).catch(() => setUser(null)).finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    setUser(await api<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }))
  }

  const logout = async () => {
    setLogoutState('pending')
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      await Promise.race([
        api('/auth/logout', { method: 'POST', signal: controller.signal }),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            controller.abort()
            reject(new Error('Logout not confirmed'))
          }, 15000)
        }),
      ])
      setUser(null)
      setLogoutState('idle')
    } catch {
      // Block protected UI without claiming that the server revoked the cookie.
      setLogoutState('error')
    } finally {
      clearTimeout(timer)
    }
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>
    {logoutState === 'pending' ? <p role="status">Выполняется выход…</p>
      : logoutState === 'error' ? <div role="alert">
        <p>Выход на сервере не подтверждён. Доступ к интерфейсу приостановлен.</p>
        <button onClick={logout}>Повторить выход</button>
      </div> : children}
  </AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is missing')
  return value
}
