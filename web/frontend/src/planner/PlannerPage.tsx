import { useEffect, useState, type FormEvent } from 'react'
import { plannerApi, type Employee, type Goal, type History, type Plan, type Task } from './transport'
import { usePlannerAccess } from './access'
import './planner.css'
import { DailyPlan, type Daily } from './DailyPlan'
import { usePlannerNavigation } from './navigation'
import { ManagerDashboard, MetricsPrompt, PlannerMetrics, PlannerStats, PlanOverview, TeamCards, TaskRows, type PlanSummary } from './Dashboard'

const labels = { draft: 'Черновик', approved: 'Подтверждён', closed: 'День закрыт' }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Не удалось выполнить запрос'
const options = (body?: unknown, method = 'POST') => ({ method, body: JSON.stringify(body) })

function TaskCard({ task, plan, role, today, busy, change }: { task: Task; plan: Plan; role: string; today: string; busy: boolean; change(path: string, body?: unknown, method?: string): Promise<boolean> }) {
  const [title, setTitle] = useState(task.title)
  const [minutes, setMinutes] = useState(String(task.planned_minutes))
  const [target, setTarget] = useState(String(task.target ?? 0))
  const [actual, setActual] = useState(String(task.actual_value))
  const [actualMinutes, setActualMinutes] = useState(String(Math.floor(task.actual_seconds / 60)))
  const [result, setResult] = useState(task.result)
  const [comment, setComment] = useState(task.comment)
  const [status, setStatus] = useState(task.status)
  const [request, setRequest] = useState(false)
  const [field, setField] = useState('planned_minutes')
  const [proposed, setProposed] = useState('')
  const [reason, setReason] = useState('')
  const closed = plan.status === 'closed' || task.status === 'moved' || task.kind === 'bitrix'
  const protectedPlan = role === 'manager' && (plan.status === 'approved' || !!task.locked)
  const planningDisabled = busy || closed || (role === 'manager' && !!task.locked)
  function cancel() {
    setTitle(task.title); setMinutes(String(task.planned_minutes)); setTarget(String(task.target ?? 0))
    setActual(String(task.actual_value)); setActualMinutes(String(Math.floor(task.actual_seconds / 60)))
    setResult(task.result); setComment(task.comment); setStatus(task.status); setRequest(false)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    const body: Record<string, unknown> = { revision: task.revision, result, comment, status }
    if (task.kind === 'quantitative') body.actual_value = Number(actual)
    if (Number(actualMinutes) !== Math.floor(task.actual_seconds / 60)) body.actual_minutes = Number(actualMinutes)
    if (title !== task.title) body.title = title
    if (Number(minutes) !== task.planned_minutes) body.planned_minutes = Number(minutes)
    if (task.kind === 'quantitative' && Number(target) !== task.target) body.target = Number(target)
    await change(`/tasks/${task.id}`, body, 'PATCH')
  }
  return <article className="pw-card" data-task-id={task.id}>
    <form onSubmit={save}>
      <div className="pw-task-heading"><h3>{task.title}</h3><span className="pw-chip">{({ todo: 'К выполнению', in_progress: 'В работе', done: 'Выполнено', moved: 'Перенесено' } as Record<string, string>)[task.status]}</span></div>
      {task.distribution_source && <p className="pw-source">{task.distribution_source.name}: {task.distribution_source.count} лидов · {task.distribution_source.dates.join(', ')}</p>}
      <fieldset className="pw-fields"><legend>План задачи</legend>
        <label>Название<input aria-label="Название задачи" value={title} onChange={e => setTitle(e.target.value)} disabled={planningDisabled} required maxLength={180} /></label>
        <label>Плановое время, мин<input aria-label="Плановое время" type="number" min="0" max="1440" value={minutes} onChange={e => setMinutes(e.target.value)} disabled={planningDisabled || protectedPlan} /></label>
        {task.kind === 'quantitative' && <label>Плановая цель<input aria-label="Плановая цель" type="number" min="0" value={target} onChange={e => setTarget(e.target.value)} disabled={planningDisabled || protectedPlan || task.distribution_target_locked} /></label>}
      </fieldset><fieldset className="pw-fields"><legend>Факт и результат</legend>
        {task.kind === 'quantitative' && <label>Фактическое количество<input aria-label="Фактическое количество" type="number" min="0" value={actual} onChange={e => setActual(e.target.value)} disabled={busy || closed} /></label>}
        <label className="pw-wide-field">Результат<textarea aria-label="Результат" value={result} onChange={e => setResult(e.target.value)} disabled={busy || closed} maxLength={4000} /></label>
        <label className="pw-wide-field">Комментарий<textarea aria-label="Комментарий" value={comment} onChange={e => setComment(e.target.value)} disabled={busy || closed} maxLength={4000} /></label>
        <label>Фактическое время, мин<input aria-label="Фактическое время" type="number" min="0" max="525600" value={actualMinutes} onChange={e => setActualMinutes(e.target.value)} disabled={busy || closed || !!task.timer_started} /></label>
        <label>Статус<select aria-label="Статус задачи" value={status} onChange={e => setStatus(e.target.value)} disabled={busy || closed}><option value="todo">К выполнению</option><option value="in_progress">В работе</option><option value="done">Выполнено</option>{task.status === 'moved' && <option value="moved">Перенесено</option>}</select></label>
      </fieldset>
      <div className="pw-actions"><button disabled={busy || closed}>Сохранить задачу</button><button className="pw-secondary" type="button" onClick={cancel} disabled={busy || closed}>Отмена</button><span>Время по серверу: {Math.floor(task.elapsed_seconds / 60)} мин {task.elapsed_seconds % 60} сек</span>
        {role === 'manager' && <button type="button" disabled={busy || closed || plan.day !== today || task.status === 'done'} onClick={() => change(`/tasks/${task.id}/timer`, { action: task.timer_started ? 'stop' : 'start' })}>{task.timer_started ? 'Остановить таймер' : 'Запустить таймер'}</button>}
        {role === 'manager' && <button className="pw-secondary" type="button" disabled={busy || closed} onClick={() => setRequest(!request)}>Запросить изменение цели / времени</button>}
      </div>
      {task.timer_started && <small>Таймер работает на сервере. Обновите план для свежего показания.</small>}
      {protectedPlan && <small>Защищённые цели и время меняются через согласование.</small>}
    </form>
    {request && <form className="pw-request" onSubmit={async e => { e.preventDefault(); if (await change(`/tasks/${task.id}/requests`, { field, proposed: Number(proposed), reason })) setRequest(false) }}>
      <label>Что изменить<select value={field} onChange={e => setField(e.target.value)}><option value="planned_minutes">Плановое время</option>{task.kind === 'quantitative' && !task.distribution_target_locked && <option value="target">Количественная цель</option>}</select></label>
      <label>Новое значение<input type="number" min="0" value={proposed} onChange={e => setProposed(e.target.value)} required /></label>
      <label>Причина<input value={reason} onChange={e => setReason(e.target.value)} required maxLength={2000} /></label>
      <button disabled={busy}>Отправить запрос</button>
      <button className="pw-secondary" type="button" onClick={() => setRequest(false)} disabled={busy}>Отмена запроса</button>
    </form>}
  </article>
}

function usePlannerResource<T>(path: string | undefined, refresh: number) {
  const key = `${path || ''}:${refresh}`
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>()
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    plannerApi<T>(path, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setState({ key, data }) })
      .catch(error => { if (!controller.signal.aborted) setState({ key, error: errorText(error) }) })
    return () => controller.abort()
  }, [path, key])
  return state?.key === key ? state : undefined
}

export function PlannerPage({ embedded = false }: { embedded?: boolean }) {
  const [selectedEmployee, setEmployee] = useState<number>()
  const [selectedDay, setDay] = useState('')
  const { view: tab, navigate: setTab } = usePlannerNavigation()
  const [busy, setBusy] = useState(false)
  const [dailyDirty,setDailyDirty]=useState(false)
  const [message, setMessage] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [employeeRefresh, setEmployeeRefresh] = useState(0)
  const [requestRefresh, setRequestRefresh] = useState(0)
  const [newTitle, setNewTitle] = useState('')
  const [newKind, setNewKind] = useState('general')
  const [newMinutes, setNewMinutes] = useState('30')
  const [newTarget, setNewTarget] = useState('1')
  const [taskQuery, setTaskQuery] = useState('')
  const [taskStatus, setTaskStatus] = useState('all')
  const { state: access } = usePlannerAccess()
  const me = access.status === 'allowed' ? access.me : undefined
  const employeeData = usePlannerResource<Employee[]>(me?.user.role === 'supervisor' ? '/employees' : undefined, employeeRefresh)
  const employees = employeeData?.data
  const employeeError = employeeData?.error
  const query = new URLSearchParams(window.location.search)
  const queryDay = query.get('day') || ''
  const day = selectedDay || (/^\d{4}-\d{2}-\d{2}$/.test(queryDay) ? queryDay : me?.today || '')
  const employee = me?.user.role === 'manager' ? me.user.id : employees?.find(item => item.id === (selectedEmployee || Number(query.get('employee'))))?.id || employees?.[0]?.id
  const plans = usePlannerResource<Omit<Plan, 'tasks'>[]>(me && employee && day && tab !== 'metrics' ? `/plans?day=${day}&employee_id=${employee}` : undefined, refresh)
  const selectedPlan = plans?.data ? plans.data[0] || null : undefined
  const overview = usePlannerResource<PlanSummary[]>(me?.user.role === 'supervisor' && day && ['home', 'employees'].includes(tab) ? `/plans?day=${day}` : undefined, refresh)
  const scopedEmployees = employees?.filter(item => !selectedEmployee || item.id === selectedEmployee)
  const overviewPlans = overview?.data && scopedEmployees ? overview.data.filter(p => scopedEmployees.some(e => e.id === p.employee_id)) : undefined
  const planData = usePlannerResource<Plan>(selectedPlan ? `/plans/${selectedPlan.id}` : undefined, refresh)
  const plan = selectedPlan === null ? null : planData?.data
  const planError = plans?.error || planData?.error
  const requestData = usePlannerResource<Goal[]>(me ? '/requests' : undefined, requestRefresh)
  const requests = requestData?.data
  const requestError = requestData?.error
  const detail = usePlannerResource<History[] | Plan>(plan && ['history', 'report'].includes(tab) && (tab !== 'report' || plan.status === 'closed') ? `/plans/${plan.id}/${tab === 'history' ? 'history' : 'report'}` : undefined, refresh)
  const history = Array.isArray(detail?.data) ? detail.data : undefined
  const report = detail?.data && !Array.isArray(detail.data) ? detail.data : undefined
  const detailError = detail?.error
  useEffect(() => {
    if (day && employee) window.history.replaceState(null, '', `${window.location.pathname}?day=${day}&employee=${employee}`)
  }, [day, employee, tab])
  async function change(path: string, body?: unknown, method = 'POST') {
    setBusy(true); setMessage('')
    try { await plannerApi(path, options(body, method)); setRefresh(value => value + 1); setRequestRefresh(value => value + 1); return true }
    catch (error) { setMessage(errorText(error)); return false }
    finally { setBusy(false) }
  }
  if (!me) return <section className="planner-web" role="status">Загрузка планировщика…</section>
  const supervisor = me.user.role === 'supervisor'
  const sectionTitle = { home: supervisor ? 'Обзор отдела' : 'Главная', employees: 'Сотрудники', plan: supervisor ? 'Планы' : 'Мой план', tasks: supervisor ? 'Задачи и прогресс' : 'Задачи', requests: 'Согласования', history: 'История', report: 'Отчёты', metrics: 'Показатели' }[tab]
  const planActions = plan && <div className="pw-actions">{dailyDirty && <span role="status">Сначала сохраните дневные показатели.</span>}{plan.status === 'draft' && <button disabled={busy || dailyDirty} onClick={() => change(`/plans/${plan.id}/${supervisor ? 'approve' : 'confirm'}`)}>{supervisor ? 'Утвердить план' : 'Подтвердить план'}</button>}{plan.status !== 'closed' && day <= me.today && <button className="pw-secondary" disabled={busy || dailyDirty} onClick={() => change(`/plans/${plan.id}/close`)}>Закрыть рабочий день</button>}</div>
  return <section className="planner-web">
    {tab !== 'metrics' && <div className={embedded ? 'pw-embedded-heading' : 'pw-heading'}>{!embedded && <div><p className="pw-eyebrow">{supervisor ? 'КОМАНДА И РЕЗУЛЬТАТЫ' : 'ВАШ РАБОЧИЙ ДЕНЬ'}</p><h1>{sectionTitle}</h1><p className="pw-muted">{supervisor ? 'Планы, нагрузка и прогресс сотрудников без лишнего шума.' : 'Всё важное — в одном месте. Сосредоточьтесь на следующем шаге.'}</p></div>}<button className="pw-secondary" disabled={busy} onClick={() => setRefresh(value => value + 1)}>Обновить план</button></div>}
    {tab !== 'metrics' && <div className="pw-toolbar">
      {supervisor && <>{employees === undefined && !employeeError && <span role="status">Загрузка сотрудников…</span>}{employees && <label>Сотрудник<select aria-label="Сотрудник" value={['home', 'employees'].includes(tab) ? selectedEmployee || 'all' : employee || ''} onChange={e => setEmployee(e.target.value === 'all' ? undefined : Number(e.target.value))}>{['home', 'employees'].includes(tab) && <option value="all">Весь отдел</option>}{employees.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><small>{employees.length} сотрудника</small></label>}{employeeError && <div role="alert">{employeeError}<button onClick={() => setEmployeeRefresh(value => value + 1)}>Повторить загрузку сотрудников</button></div>}</>}
      <label>Дата плана<input aria-label="Дата плана" type="date" value={day} onChange={e => setDay(e.target.value)} /></label>{(!supervisor || !['home', 'employees'].includes(tab) || !!selectedEmployee) && <span className="pw-chip">{plan ? labels[plan.status] : 'План не выбран'}</span>}
    </div>}
    {!['home', 'employees', 'metrics'].includes(tab) && <nav className="pw-tabs" aria-label="Разделы плана">{([['plan', 'План и задачи'], ['requests', 'Согласования'], ['history', 'История'], ['report', 'Отчёт']] as const).map(([key, label]) => <button key={key} className={key === tab ? 'pw-selected' : 'pw-secondary'} onClick={() => setTab(key)}>{label}</button>)}</nav>}
    {message && <div className="pw-error" role="alert">{message}<button onClick={() => setRefresh(value => value + 1)}>Обновить данные</button></div>}
    {busy && <p role="status">Сохраняем…</p>}
    {planError && <div className="pw-error" role="alert">{planError}<button onClick={() => setRefresh(value => value + 1)}>Повторить загрузку плана</button></div>}
    {['home', 'employees'].includes(tab) && <>
      {tab === 'home' && <PlannerStats supervisor={supervisor} plan={plan} plans={overviewPlans} employees={scopedEmployees} requests={requests} />}
      {overview?.error && <div className="pw-error" role="alert">Обзор отдела не загружен: {overview.error}<button onClick={() => setRefresh(value => value + 1)}>Повторить загрузку обзора</button></div>}
      {supervisor && scopedEmployees && <TeamCards employees={scopedEmployees} plans={overviewPlans} day={day} open={id => { setEmployee(id); setTab('plan') }} />}
      {!supervisor && plan && <ManagerDashboard plan={plan} today={me.today} busy={busy} actions={planActions} change={change} />}
      {!supervisor && plan === null && <section className="pw-card pw-empty"><h2>План рабочего дня</h2><p>На выбранную дату плана нет.</p><button disabled={busy} onClick={() => change('/plans', { day, employee_id: employee })}>Создать план</button></section>}
      {!supervisor && plan === undefined && !planError && <p role="status">Загрузка плана…</p>}
      {supervisor && plan && <section className="pw-card pw-today"><div className="pw-section-heading"><div><h2>Задачи на сегодня</h2><p className="pw-muted">Выбранный план · {plan.employee_name}</p></div><button className="pw-text-button" onClick={() => setTab('tasks')}>Все задачи →</button></div><TaskRows tasks={plan.tasks.slice(0, 3)} employee={plan.employee_name} /></section>}
      {supervisor && <section className="pw-card pw-approval-summary"><div><h2>Согласования</h2><p className="pw-muted">{requests ? `${requests.filter(r => r.status === 'pending').length} запросов ожидают решения` : requestError ? 'Не удалось загрузить запросы' : 'Загрузка запросов…'}</p></div><button className="pw-secondary" onClick={() => setTab('requests')}>Открыть согласования →</button></section>}
      <MetricsPrompt />
    </>}
    {tab === 'metrics' && <PlannerMetrics />}
    {['plan', 'tasks'].includes(tab) && <>
      {plan === undefined && employee && !planError && <p role="status">Загрузка плана…</p>}
      {plan === null && <div className="pw-card"><p>На выбранную дату плана нет.</p><button disabled={busy} onClick={() => change('/plans', { day, employee_id: employee })}>Создать план</button></div>}
      {plan && <>{tab === 'plan' && <DailyPlan key={`${plan.id}:${plan.status}`} plan={plan} onDirtyChange={setDailyDirty} />}{tab === 'plan' && <div className="pw-plan-summary"><PlanOverview plan={plan} actions={planActions} /><section className="pw-card"><h2>Состав плана</h2><TaskRows tasks={plan.tasks} /><p className="pw-notice">Защищённые цели и импортированные количества сохраняют действующие серверные ограничения.</p></section></div>}
        {tab === 'tasks' && <div className="pw-toolbar"><label>Поиск задач<input aria-label="Поиск задач" value={taskQuery} onChange={e => setTaskQuery(e.target.value)} /></label><label>Статус задач<select aria-label="Фильтр статуса задач" value={taskStatus} onChange={e => setTaskStatus(e.target.value)}><option value="all">Все статусы</option><option value="todo">В плане</option><option value="in_progress">В работе</option><option value="done">Завершены</option><option value="moved">Перенесены</option></select></label></div>}
        {plan.tasks.filter(task => tab !== 'tasks' || (task.title.toLowerCase().includes(taskQuery.toLowerCase()) && (taskStatus === 'all' || task.status === taskStatus))).map(task => <TaskCard key={`${task.id}-${task.revision}`} task={task} plan={plan} role={me.user.role} today={me.today} busy={busy} change={change} />)}
        {tab === 'tasks' && !plan.tasks.some(task => task.title.toLowerCase().includes(taskQuery.toLowerCase()) && (taskStatus === 'all' || task.status === taskStatus)) && <p className="pw-empty">По выбранным условиям задач нет.</p>}
        {plan.status !== 'closed' && <form className="pw-card" onSubmit={async e => { e.preventDefault(); if (await change(`/plans/${plan.id}/tasks`, { title: newTitle, kind: newKind, planned_minutes: Number(newMinutes), target: newKind === 'quantitative' ? Number(newTarget) : null })) setNewTitle('') }}><h2>Добавить задачу</h2><div className="pw-fields"><label>Название новой задачи<input aria-label="Название новой задачи" value={newTitle} onChange={e => setNewTitle(e.target.value)} required maxLength={180} /></label><label>Тип<select aria-label="Тип новой задачи" value={newKind} onChange={e => setNewKind(e.target.value)}><option value="general">Обычная</option><option value="quantitative">Количественная</option></select></label><label>Плановое время, мин<input aria-label="Время новой задачи" type="number" min="0" max="1440" value={newMinutes} onChange={e => setNewMinutes(e.target.value)} required /></label>{newKind === 'quantitative' && <label>Количественная цель<input aria-label="Цель новой задачи" type="number" min="0" value={newTarget} onChange={e => setNewTarget(e.target.value)} required /></label>}</div><div className="pw-actions"><button disabled={busy}>Добавить задачу</button><button type="button" className="pw-secondary" disabled={busy} onClick={() => { setNewTitle(''); setNewKind('general'); setNewMinutes('30'); setNewTarget('1') }}>Отмена создания</button></div></form>}
      </>}
    </>}
    {tab === 'requests' && <div className="pw-card"><h2>Запросы на изменение целей</h2>{requestError && <div role="alert">{requestError}<button onClick={() => setRequestRefresh(value => value + 1)}>Повторить загрузку запросов</button></div>}{!requests && !requestError && <p>Загрузка запросов…</p>}{requests?.length === 0 && <p>Запросов пока нет.</p>}{requests?.map(item => <article className="pw-request" key={item.id}><strong>{item.title} · {item.employee_name}</strong><p>{item.field === 'target' ? 'Цель' : 'Время'}: {item.old_value} → {item.proposed} · {item.status === 'pending' ? 'Ожидает решения' : item.status === 'approved' ? 'Утверждено' : item.status === 'rejected' ? 'Отклонено' : 'Отменено'}</p><p>{item.reason}</p>{me.user.role === 'supervisor' && item.status === 'pending' && <div className="pw-actions"><button disabled={busy} onClick={() => change(`/requests/${item.id}/decision`, { decision: 'approved', comment: '' })}>Утвердить изменение</button><button className="pw-secondary" disabled={busy} onClick={() => change(`/requests/${item.id}/decision`, { decision: 'rejected', comment: '' })}>Отклонить</button></div>}</article>)}</div>}
    {tab === 'history' && <div className="pw-card"><h2>История плана</h2>{detailError && <p role="alert">{detailError}</p>}{!plan && <p>Выберите существующий план.</p>}{plan && !history && !detailError && <p>Загрузка истории…</p>}{history?.map(item => <p className="pw-history" key={item.id}>{new Date(item.created_at * 1000).toLocaleString('ru-RU')} · {item.actor_name || 'Система'} · {({ task_created: 'Задача создана', task_updated: 'Задача изменена', plan_created: 'План создан', plan_confirmed: 'План подтверждён', plan_approved: 'План утверждён', timer_start: 'Таймер запущен', timer_stop: 'Таймер остановлен', day_closed: 'День закрыт', goal_requested: 'Изменение запрошено', goal_approved: 'Изменение утверждено' } as Record<string, string>)[item.action] || 'Изменение плана'}</p>)}</div>}
    {tab === 'report' && <div className="pw-card"><h2>Сохранённый отчёт</h2>{plan?.status !== 'closed' && <p>Отчёт доступен после закрытия выбранного дня.</p>}{detailError && <p role="alert">{detailError}</p>}{plan?.status === 'closed' && !report && !detailError && <p>Загрузка отчёта…</p>}{report && <>{(report as Plan & { daily?: Daily }).daily && <DailyPlan plan={report} snapshot={(report as Plan & { daily?: Daily }).daily} />}<p>{report.employee_name} · {report.day} · Выполнено {report.summary.done} из {report.summary.total}</p>{report.tasks.map(task => <div className="pw-history" key={task.id}><strong>{task.title}</strong><p>Факт: {task.kind === 'quantitative' ? task.actual_value : '—'} · {Math.floor(task.elapsed_seconds / 60)} мин</p><p>{task.result}</p><p>{task.comment}</p></div>)}</>}</div>}
    <p className="pw-footnote">{me.crm.message}</p>
  </section>
}
