import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/WorkspaceUI'
import { roleLabels } from '../lib/format'
import { PlannerPage } from '../planner/PlannerPage'
import { PlannerAccessGate } from '../planner/PlannerAccess'
import { ManagersPage } from './ManagersPage'

export function EmployeesPage() {
  const { user } = useAuth()
  if (user?.role === 'manager') return <Card><h1>Сотрудники</h1><p role="alert">Просмотр сотрудников доступен руководителю и администратору.</p></Card>
  return <><PageHeader title="Сотрудники" subtitle="Команда, рабочие графики и планы" /><p className="pw-notice">Учётные записи LeadFlow и сотрудники Planner пока хранятся отдельно. Доступ к планам определяется явной серверной привязкой, а не именем или совпадением ID.</p><div className="ui-source-heading"><h2>Учётные записи и графики</h2><span>Источник: LeadFlow · управление по действующим правам</span></div><ManagersPage embedded />{import.meta.env.VITE_WORKSPACE_ENABLED !== '0' && <PlannerAccessGate embedded><div className="ui-source-heading"><h2>Планы сотрудников</h2><span>Источник: Planner · отдельные идентификаторы сотрудников</span></div><PlannerPage embedded /></PlannerAccessGate>}</>
}
export function SettingsPage() {
  const { user } = useAuth()
  return <><PageHeader title="Настройки" subtitle="Профиль текущей учётной записи" /><Card><h2>Мой профиль</h2><dl className="ui-profile-data"><div><dt>Имя</dt><dd>{user?.full_name}</dd></div><div><dt>Email</dt><dd>{user?.email}</dd></div><div><dt>Роль</dt><dd>{user && roleLabels[user.role]}</dd></div></dl><p className="pw-muted">Источник: текущая серверная сессия LeadFlow. Управление сотрудниками доступно в разделе «Сотрудники» в пределах ваших прав. Управление доступом выполняется уполномоченным администратором.</p></Card></>
}
