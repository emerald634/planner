import { ArrowRight, Waypoints } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Redirect } from 'wouter'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Redirect to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try { await login(email, password) } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось войти') }
    finally { setBusy(false) }
  }
  return <div className="login-page">
    <section className="login-visual">
      <div className="brand brand-light"><span className="brand-mark">Р</span><span>Рабочее пространство</span></div>
      <div className="visual-copy"><span className="eyebrow">ЕДИНОЕ РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Лиды, планы<br />и команда.</h1><p>Один вход для работы с лидами, задачами и результатами рабочего дня.</p></div>
      <div className="route-art"><span /><span /><span /><Waypoints size={28} /></div>
    </section>
    <section className="login-form-wrap"><form onSubmit={submit} className="login-form">
      <div><span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span><h2>Вход в систему</h2><p>Используйте рабочую учётную запись</p></div>
      <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></label>
      <label>Пароль<input type="password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {error && <div className="alert">{error}</div>}
      <button className="button button-primary button-wide" disabled={busy}>{busy ? 'Входим…' : 'Войти'}<ArrowRight size={18} /></button>
      <small>Доступ предоставляется администратором системы</small>
    </form></section>
  </div>
}
