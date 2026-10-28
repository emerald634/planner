import { BarChart3, CheckSquare, ClipboardList, FileText, Home, LogOut, Settings, ShieldCheck, Users, Waypoints } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'wouter'
import { useAuth } from '../auth/AuthContext'
import { roleLabels } from '../lib/format'
import '../planner/planner.css'
import './workspace.css'
import { usePlannerAccess } from '../planner/access'

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const [location] = useLocation()
  const { state: plannerAccess } = usePlannerAccess()
  const local = import.meta.env.VITE_LOCAL_PLANNER_MVP === '1'
  const planner = import.meta.env.VITE_WORKSPACE_ENABLED !== '0'
  const plannerAllowed = planner && plannerAccess.status === 'allowed'
  const links = [
    { to: '/', label: 'Главная', Icon: Home },
    { to: '/leads', label: 'Лиды', Icon: Waypoints },
    ...(plannerAllowed ? [{ to: '/distributions', label: 'Недозвоны', Icon: Waypoints }, { to: '/planner', label: 'План дня', Icon: ClipboardList }, { to: '/planner/tasks', label: 'Задачи', Icon: CheckSquare }] : []),
    ...(user?.role !== 'manager' ? [{ to: '/managers', label: 'Сотрудники', Icon: Users }] : []),
    ...(plannerAllowed ? [{ to: '/planner/approvals', label: 'Согласования', Icon: ShieldCheck }] : []),
    { to: '/statistics', label: 'Аналитика', Icon: BarChart3 },
    ...(plannerAllowed ? [{ to: '/planner/history', label: 'История и отчёты', Icon: FileText }] : []),
    { to: '/settings', label: 'Настройки', Icon: Settings },
  ]
  const selected = location.startsWith('/leads/') ? '/leads' : location === '/planner/reports' ? '/planner/history' : location
  const title = links.find(link => link.to === selected)?.label || (location.startsWith('/planner') ? 'План дня' : 'Рабочее пространство')
  const initial = user?.full_name.slice(0, 1).toUpperCase()
  return <div className="pw-workspace unified-workspace">
    <aside className="pw-sidebar" data-testid="workspace-sidebar">
      <Link href="/" className="pw-brand" aria-label="Главная — Рабочее пространство"><span className="pw-brand-mark">Р</span><span>Рабочее пространство<small>ЛИДЫ · ПЛАНЫ · ЗАДАЧИ</small></span></Link>
      <p className="pw-nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
      <nav aria-label="Основное меню">{links.map(({ to, label, Icon }) => <Link key={to} href={to} className={selected === to ? 'pw-nav-selected' : ''} aria-current={selected === to ? 'page' : undefined}><Icon /><span>{label}</span></Link>)}</nav>
      <div className="pw-sidebar-bottom"><small><i />{local ? 'Локальный просмотр · искусственные данные' : 'Рабочее пространство'}</small></div>
      <div className="pw-profile"><span className="pw-avatar">{initial}</span><div><strong>{user?.full_name}</strong><small>{user && roleLabels[user.role]}</small></div><button onClick={logout} title="Выйти" aria-label="Выйти"><LogOut /></button></div>
    </aside>
    <div className="pw-main-shell"><header className="pw-topbar"><span>Рабочее пространство <b>/ {title}</b></span><div><span className="pw-top-date">{new Intl.DateTimeFormat('ru-RU', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Europe/Moscow' }).format(new Date())}</span><span className="pw-avatar pw-small-avatar" title={user?.full_name}>{initial}</span></div></header>
      <main className="pw-content">{local && <div className="pw-local-banner"><b>ЛОКАЛЬНО</b><span>Искусственные данные · бизнес-API подключён · изменения CRM отключены</span></div>}{children}</main>
    </div>
  </div>
}
