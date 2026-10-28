import { CheckCircle2, Clock3, Users, Waypoints } from 'lucide-react'
import { Link } from 'wouter'
import { useAuth } from '../auth/AuthContext'
import { Card, ErrorState, LoadingState, Table } from '../components/WorkspaceUI'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { useResource } from '../lib/useResource'
import { dateTime } from '../lib/format'
import { PlannerPage } from '../planner/PlannerPage'
import { PlannerAccessGate } from '../planner/PlannerAccess'
import type { LeadList, Stats } from '../types'

function validStats(value: unknown) {
  return !!value && typeof value === 'object' && ['total_leads','assigned_leads','pending_sync','managers'].every(key => typeof (value as Record<string,unknown>)[key] === 'number' && Number.isFinite((value as Record<string,unknown>)[key]))
}
function validLeads(value: unknown) {
  return !!value && typeof value === 'object' && Array.isArray((value as LeadList).items) && typeof (value as LeadList).total === 'number'
}
export function LeadFlowSummary({ distribution = false }: { distribution?: boolean }) {
  const resource = useResource<Stats>('/stats/summary', validStats)
  const stats = resource.data
  const cards = [ ['Всего лидов LeadFlow', stats?.total_leads, Waypoints, 'blue'], ['Назначено в LeadFlow', stats?.assigned_leads, CheckCircle2, 'green'], ['Ожидают синхронизации LeadFlow', stats?.pending_sync, Clock3, 'orange'], ['Активных менеджеров LeadFlow', stats?.managers, Users, 'violet'] ] as const
  const assigned = stats ? stats.total_leads ? Math.round(stats.assigned_leads / stats.total_leads * 100) : 0 : undefined
  return <section aria-label="Сводка лидов"><div className="ui-source-heading"><h2>Лиды LeadFlow</h2><span>Источник: LeadFlow API · доступная вашему пользователю область</span></div>{resource.loading && <LoadingState text="Загрузка сводки лидов…" />}{resource.error && <ErrorState title="Сводка лидов недоступна" message={resource.error} retry={resource.retry} retryLabel="Повторить сводку лидов" />}<div className="pw-stats">{cards.map(([title,value,Icon,tone]) => <Card className="pw-stat" key={title}><div className="pw-stat-top"><span>{title}</span><span className={`pw-icon-tile pw-${tone}`}><Icon /></span></div><strong>{value ?? 'Нет данных'}</strong><small>Источник: LeadFlow</small></Card>)}</div>{distribution && <Card><h2>Назначение лидов LeadFlow</h2><p className="ui-number">{assigned === undefined ? 'Нет данных' : `${assigned}% назначено`}</p><p className="pw-muted">Доля назначенных лидов среди доступных лидов LeadFlow. Не является прогрессом задач или показателем звонков.</p></Card>}</section>
}
export function RecentLeads() {
  const resource = useResource<LeadList>('/leads?page_size=5', validLeads)
  return <Card className="ui-recent-leads"><div className="pw-section-heading"><h2>Последние лиды</h2><Link href="/leads" className="text-link">Все лиды →</Link></div>{resource.loading && <LoadingState text="Загрузка последних лидов…" />}{resource.error && <ErrorState title="Последние лиды недоступны" message={resource.error} retry={resource.retry} retryLabel="Повторить последние лиды" />}{resource.data && <Table><thead><tr><th>Контакт</th><th>Менеджер</th><th>Создан</th><th>Статус синхронизации</th></tr></thead><tbody>{resource.data.items.map(lead => <tr key={lead.id}><td><Link className="lead-name" href={`/leads/${lead.id}`}>{lead.name || 'Без имени'}</Link><small>{lead.phone}</small></td><td>{lead.manager?.full_name || 'Не назначен'}</td><td>{dateTime(lead.created_at)}</td><td><StatusBadge status={lead.sync_status} /></td></tr>)}{!resource.data.items.length && <tr><td colSpan={4}>Лидов пока нет.</td></tr>}</tbody></Table>}</Card>
}
export function DashboardPage() {
  const { user } = useAuth()
  return <><PageHeader title="Главная" subtitle={user?.role === 'manager' ? 'Лиды, рабочий план и ближайшие задачи' : 'Лиды, команда, планы и согласования'} /><LeadFlowSummary />{import.meta.env.VITE_WORKSPACE_ENABLED !== '0' && <PlannerAccessGate embedded><div className="ui-source-heading"><h2>{user?.role === 'manager' ? 'Мой рабочий день' : 'Планы и прогресс отдела'}</h2><span>Источник: Planner API · отдельный учёт задач и времени</span></div><PlannerPage embedded /></PlannerAccessGate>}<RecentLeads /></>
}
