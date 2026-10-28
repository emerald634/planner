import { BarChart3, CheckSquare, ClipboardList, Clock3, ShieldCheck, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Employee, Goal, Plan, Task } from './transport'
import { usePlannerNavigation } from './navigation'

export const planLabels = { draft: 'Черновик', approved: 'Подтверждён', closed: 'День закрыт' }
export const taskLabels: Record<string, string> = { todo: 'В плане', in_progress: 'В работе', done: 'Завершена', moved: 'Перенесена' }
export const duration = (seconds: number) => `${Math.floor(seconds / 3600)} ч ${String(Math.floor(seconds / 60) % 60).padStart(2, '0')} мин`
export type PlanSummary = Omit<Plan, 'tasks'>

function Stat({ title, value, hint, tone, icon }: { title: string; value: ReactNode; hint: string; tone: string; icon: ReactNode }) {
  return <article className="pw-card pw-stat"><div className="pw-stat-top"><span>{title}</span><span className={`pw-icon-tile pw-${tone}`}>{icon}</span></div><strong>{value}</strong><small>{hint}</small></article>
}
export function PlannerStats({ supervisor, plan, plans, employees, requests }: { supervisor: boolean; plan?: Plan | null; plans?: PlanSummary[]; employees?: Employee[]; requests?: Goal[] }) {
  const total = plans?.reduce((sum, p) => sum + p.summary.total, 0)
  const done = plans?.reduce((sum, p) => sum + p.summary.done, 0)
  return <div className="pw-stats">{supervisor ? <>
    <Stat title="Сотрудники" value={employees?.length ?? 'Нет данных'} hint="Активные менеджеры отдела" tone="blue" icon={<Users />} />
    <Stat title="Подтверждённые планы" value={plans?.filter(p => p.status === 'approved').length ?? 'Нет данных'} hint="На выбранную дату" tone="green" icon={<ShieldCheck />} />
    <Stat title="Выполнено задач" value={plans ? `${done} из ${total}` : 'Нет данных'} hint="По загруженным планам" tone="orange" icon={<CheckSquare />} />
    <Stat title="Требует согласования" value={requests?.filter(r => r.status === 'pending').length ?? 'Нет данных'} hint="Ожидают решения руководителя" tone="violet" icon={<ClipboardList />} />
  </> : <>
    <Stat title="Задачи на сегодня" value={plan ? plan.summary.total : plan === null ? '0' : 'Нет данных'} hint="Из выбранного рабочего плана" tone="blue" icon={<CheckSquare />} />
    <Stat title="Завершено задач" value={plan ? `${plan.summary.done} из ${plan.summary.total}` : 'Нет данных'} hint="Прогресс выбранного дня" tone="green" icon={<ShieldCheck />} />
    <Stat title="Плановое время" value={plan ? `${plan.summary.planned_minutes} мин` : 'Нет данных'} hint="Сумма плановых интервалов" tone="orange" icon={<ClipboardList />} />
    <Stat title="Фактическое время" value={plan ? duration(plan.summary.actual_seconds) : 'Нет данных'} hint="Снимок серверного состояния" tone="violet" icon={<Clock3 />} />
  </>}</div>
}
export function Progress({ done, total }: { done: number; total: number }) {
  const value = total ? Math.round(done / total * 100) : 0
  return <div className="pw-progress" role="progressbar" aria-label="Прогресс задач" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${value}%` }} /></div>
}
export function PlanOverview({ plan, actions }: { plan: Plan; actions?: ReactNode }) {
  const value = plan.summary.total ? Math.round(plan.summary.done / plan.summary.total * 100) : 0
  return <section className="pw-card pw-plan-overview"><div className="pw-section-heading"><h2>План рабочего дня</h2><span className={`pw-chip ${plan.status}`}>{planLabels[plan.status]}</span></div><p className="pw-muted">{plan.employee_name} · {plan.day}</p><div className="pw-plan-number">{value}<span>%</span><small>задач завершено</small></div><Progress done={plan.summary.done} total={plan.summary.total} /><div className="pw-breakdown"><span>Завершено <b>{plan.summary.done}</b></span><span>В работе <b>{plan.tasks.filter(t => t.status === 'in_progress').length}</b></span><span>В плане <b>{plan.tasks.filter(t => t.status === 'todo').length}</b></span></div><div className="pw-card-foot"><span>План: {plan.summary.planned_minutes} мин</span><span>Факт: {duration(plan.summary.actual_seconds)}</span></div>{actions}</section>
}
export function TaskRows({ tasks, employee }: { tasks: Task[]; employee?: string }) {
  const { navigate } = usePlannerNavigation()
  return <div className="pw-task-list">{!tasks.length && <p className="pw-empty">Задач пока нет. Добавьте задачу в план рабочего дня.</p>}{tasks.map(task => <div className="pw-task-row" key={task.id}><span className={`pw-task-dot ${task.status}`} aria-hidden="true">{task.status === 'done' ? '✓' : ''}</span><div className="pw-task-name"><button className="pw-text-button" onClick={() => { navigate('tasks'); requestAnimationFrame(() => document.querySelector(`[data-task-id="${task.id}"]`)?.scrollIntoView({ block: 'center' })) }}>{task.title}</button><small>{employee && `${employee} · `}{task.distribution_source ? `${task.distribution_source.name} · ${task.distribution_source.count} лидов` : 'Задача рабочего дня'}</small></div><span className={`pw-chip ${task.status}`}>{taskLabels[task.status]}</span><span className="pw-task-time">{task.planned_minutes} мин</span></div>)}</div>
}
export function ManagerDashboard({ plan, today, busy, actions, change }: { plan: Plan; today: string; busy: boolean; actions: ReactNode; change(path: string, body?: unknown): Promise<boolean> }) {
  const { navigate } = usePlannerNavigation()
  const current = plan.tasks.find(t => t.timer_started !== null) || plan.tasks.find(t => t.status === 'in_progress') || plan.tasks.find(t => t.status === 'todo')
  const canTime = current && plan.day === today && plan.status !== 'closed' && current.kind !== 'bitrix' && !['done', 'moved'].includes(current.status)
  return <><div className="pw-dashboard-grid"><section className="pw-card pw-current-card"><div className="pw-section-heading"><h2>Текущая задача</h2><span className={current?.timer_started ? 'pw-live-label' : 'pw-muted'}>{current?.timer_started ? '● Таймер запущен' : current ? taskLabels[current.status] : 'Нет активной задачи'}</span></div><p className="pw-eyebrow">ИЗ ВЫБРАННОГО ПЛАНА</p><h3>{current?.title || 'Можно выбрать следующую задачу'}</h3><p className="pw-muted">{current?.distribution_source ? `${current.distribution_source.name} · ${current.distribution_source.dates.join(', ')} · ${current.distribution_source.count} лидов` : 'Задачи и результаты рабочего дня'}</p><div className="pw-current-main"><div className="pw-timer">{current ? `${duration(current.elapsed_seconds)} ${current.elapsed_seconds % 60} сек` : '—'}<small>снимок серверного таймера</small></div>{current?.kind === 'quantitative' && <div className="pw-current-target"><strong>{current.actual_value}<span> / {current.target}</span></strong><small>факт / плановая цель</small></div>}</div><div className="pw-current-actions">{canTime && <button disabled={busy} onClick={() => change(`/tasks/${current.id}/timer`, { action: current.timer_started ? 'stop' : 'start' })}>{current.timer_started ? 'Остановить таймер' : 'Запустить таймер'}</button>}<button className="pw-secondary" onClick={() => navigate('tasks')}>К задаче →</button><small>Учёт времени на сервере</small></div></section><PlanOverview plan={plan} actions={actions} /></div><section className="pw-card pw-today"><div className="pw-section-heading"><div><h2>Задачи на сегодня</h2><p className="pw-muted">Ближайшие шаги вашего дня</p></div><button className="pw-text-button" onClick={() => navigate('tasks')}>Все задачи →</button></div><TaskRows tasks={plan.tasks.slice(0, 3)} /></section></>
}
export function TeamCards({ employees, plans, day, open }: { employees: Employee[]; plans?: PlanSummary[]; day: string; open(id: number): void }) {
  return <section className="pw-card"><div className="pw-section-heading"><h2>Команда сегодня</h2><span className="pw-chip">{day}</span></div><div className="pw-employee-grid">{!employees.length && <p className="pw-empty">Активных менеджеров нет.</p>}{employees.map(employee => {
    const plan = plans?.find(p => p.employee_id === employee.id)
    return <article className="pw-employee" key={employee.id}><div className="pw-employee-top"><span className="pw-avatar">{employee.name.slice(0, 1)}</span><div><h3>{employee.name}</h3><small>Менеджер · {day}</small></div><span className={`pw-chip ${plan?.status || ''}`}>{plan ? planLabels[plan.status] : plans ? 'Нет плана' : 'Нет данных'}</span></div>{plan ? <><div className="pw-employee-numbers"><div><strong>{plan.summary.done} / {plan.summary.total}</strong><small>задач завершено</small></div><div><strong>{duration(plan.summary.actual_seconds)}</strong><small>фактическое время</small></div></div><Progress done={plan.summary.done} total={plan.summary.total} /></> : <p className="pw-empty">{plans ? 'На выбранную дату плана нет.' : 'Планы ещё не загружены.'}</p>}<button className="pw-text-button" onClick={() => open(employee.id)}>Посмотреть план →</button></article>
  })}</div></section>
}
export function MetricsPrompt() {
  const { navigate } = usePlannerNavigation()
  return <section className="pw-metrics-prompt"><span className="pw-icon-tile pw-blue"><BarChart3 /></span><div><h3>Картина шире одного дня</h3><p>Показатели звонков и консультаций — в отдельном разделе.</p></div><button className="pw-text-button" onClick={() => navigate('metrics')}>Перейти к показателям →</button></section>
}
export function PlannerMetrics() {
  return <><div className="pw-notice">{ 'Bitrix24 и телефония не подключены. Факты, прогресс и аналитика звонков недоступны.' }</div><div className="pw-metric-grid">{['Честные наборы', 'Дозвоны по лидам', 'Консультации', 'Прозвон клиентов', 'Скорость первого звонка', 'Перезвоны вовремя'].map((title, index) => <article className="pw-card" key={title}><div className="pw-section-heading"><span className={`pw-icon-tile pw-${index % 2 ? 'green' : 'blue'}`}><BarChart3 /></span><span className="pw-chip">Не подключено</span></div><h2>{title}</h2><div className="pw-no-data">Нет данных</div><p className="pw-muted">Источник: Bitrix24 / телефония</p><small>Расчёт показателя не выполняется</small></article>)}</div></>
}
