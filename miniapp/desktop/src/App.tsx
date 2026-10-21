import { useEffect, useState } from 'react';
import type { Plan, Task } from '../../src/types';
import { day, managers, plans, snapshotTime } from './fixtures';
import { metrics, normLabel, type Period } from './metrics';

type Role = 'manager' | 'supervisor';
type Route = 'home' | 'plan' | 'tasks' | 'metrics' | 'active-calls' | 'closed-calls' | 'history' | 'reports' | 'settings' | 'employees' | 'approvals';
const icons: Record<string, string> = {
  home: 'M3 10 12 3l9 7v11h-6v-7H9v7H3Z', plan: 'M8 3h8v4H8ZM6 5H4v17h16V5h-2M8 12h8M8 17h6',
  tasks: 'm3 7 2 2 4-4m3 2h9M3 15l2 2 4-4m3 2h9', metrics: 'M4 20V10m8 10V4m8 16v-7',
  calls: 'M7 3H3c0 10 8 18 18 18v-4l-5-2-3 3-7-7 3-3Z', history: 'M3 11a9 9 0 1 1 2 7M3 4v7h7m2-4v6l4 2',
  reports: 'M4 3h12l4 4v14H4ZM8 11h8M8 15h8M8 7h3', settings: 'M12 3v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2m8-8 2-2M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  employees: 'M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M2 21v-4a5 5 0 0 1 5-4h4a5 5 0 0 1 5 4v4m0-17a4 4 0 0 1 0 8m3 2a5 5 0 0 1 3 4v3',
  approvals: 'M12 3 3 7v6c0 5 9 9 9 9s9-4 9-9V7Zm-5 9 3 3 7-7',
};
function Icon({ name }: { name: string }) { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={icons[name] || icons.plan} /></svg>; }
const menu: Record<Role, [Route, string, string][]> = {
  manager: [['home', 'Главная', 'home'], ['plan', 'Мой план', 'plan'], ['tasks', 'Задачи', 'tasks'], ['metrics', 'Показатели', 'metrics'], ['active-calls', 'Обзвон действующих', 'calls'], ['closed-calls', 'Обзвон завершённых', 'calls'], ['history', 'История', 'history'], ['reports', 'Отчёты', 'reports'], ['settings', 'Настройки', 'settings']],
  supervisor: [['home', 'Обзор отдела', 'home'], ['employees', 'Сотрудники', 'employees'], ['plan', 'Планы', 'plan'], ['tasks', 'Задачи и прогресс', 'tasks'], ['metrics', 'Показатели', 'metrics'], ['approvals', 'Согласования', 'approvals'], ['history', 'История', 'history'], ['reports', 'Отчёты', 'reports']],
};
const planStatus = { draft: 'Черновик', approved: 'Подтверждён', closed: 'День закрыт' };
const taskStatus = { todo: 'В плане', in_progress: 'В работе', done: 'Завершена', moved: 'Перенесена' };
function duration(seconds: number) { const minutes = Math.floor(seconds / 60); return `${Math.floor(minutes / 60)} ч ${String(minutes % 60).padStart(2, '0')} мин`; }
function TaskRows({ items, showEmployee = false }: { items: Task[]; showEmployee?: boolean }) { return <div className="task-list">{items.map(task => <div className="task-row" key={task.id}>
  <span className={`task-dot ${task.status}`} aria-hidden="true">{task.status === 'done' ? '✓' : ''}</span>
  <div className="task-name"><strong>{task.title}</strong><small>{showEmployee && `${managers.find(m => m.id === task.employee_id)?.name} · `}{task.distribution_source ? `Источник: ${task.distribution_source.name} · ${task.target} лидов` : 'Задача рабочего дня'}</small></div>
  <span className={`badge ${task.status}`}>{taskStatus[task.status]}</span><span className="task-time">{task.planned_minutes} мин</span>
</div>)}</div>; }
function Stat({ title, value, hint, tone = 'blue', icon = 'metrics' }: { title: string; value: string; hint: string; tone?: string; icon?: string }) {
  return <article className="stat card"><div className="stat-top"><span>{title}</span><span className={`icon-tile ${tone}`}><Icon name={icon} /></span></div><strong className="stat-value">{value}</strong><small>{hint}</small></article>;
}
function Progress({ value }: { value: number }) { return <div className="progress" role="progressbar" aria-label="Прогресс задач" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${value}%` }} /></div>; }
function PlanCard({ plan }: { plan: Plan }) { const percent = Math.round(plan.summary.done / plan.summary.total * 100); return <section className="card plan-card">
  <div className="section-heading"><h2>План рабочего дня</h2><span className={`badge ${plan.status}`}>{planStatus[plan.status]}</span></div>
  <p className="muted">{plan.employee_name} · 21 октября</p><div className="plan-number">{percent}<span>%</span><small>задач завершено</small></div>
  <Progress value={percent} /><div className="plan-breakdown"><span><i className="legend green" />Завершено <b>{plan.summary.done}</b></span><span><i className="legend blue" />В работе <b>{plan.tasks.filter(t => t.status === 'in_progress').length}</b></span><span><i className="legend" />В плане <b>{plan.tasks.filter(t => t.status === 'todo').length}</b></span></div>
  <div className="card-foot">План: {plan.summary.planned_minutes} мин <span>Факт: {duration(plan.summary.actual_seconds)}</span></div>
</section>; }
export default function App() {
  const [role, setRole] = useState<Role>('manager');
  const [route, setRoute] = useState<Route>('home');
  const [employee, setEmployee] = useState('all');
  const [period, setPeriod] = useState<Period>('day');
  const [metricDay, setMetricDay] = useState(day);
  useEffect(() => { const handler = () => { const value = location.hash.replace('#/', ''); if (menu[role].some(([id]) => id === value)) setRoute(value as Route); }; handler(); window.addEventListener('hashchange', handler); return () => window.removeEventListener('hashchange', handler); }, [role]);
  const navigate = (value: Route) => { setRoute(value); location.hash = '/' + value; };
  const scoped = role === 'manager' ? plans.filter(p => p.employee_id === 101) : plans.filter(p => employee === 'all' || p.employee_id === Number(employee));
  const plan = scoped[0]; const items = scoped.flatMap(p => p.tasks); const done = items.filter(t => t.status === 'done').length;
  const current = role === 'manager' ? plan.tasks.find(t => t.timer_started !== null) : undefined;
  const title = menu[role].find(([id]) => id === route)?.[1] || 'Главная';
  function switchRole(value: Role) { setRole(value); setEmployee('all'); navigate('home'); }
  return <div className="workspace" data-demo="true">
    <aside className="sidebar"><a className="brand" href="#/home" onClick={() => navigate('home')}><span className="brand-mark">П</span><span>План дня<small>РАБОЧЕЕ ПРОСТРАНСТВО</small></span></a>
      <p className="nav-caption">{role === 'manager' ? 'ЛИЧНЫЙ КАБИНЕТ' : 'УПРАВЛЕНИЕ ОТДЕЛОМ'}</p>
      <nav aria-label="Основное меню">{menu[role].map(([id, label, icon]) => <a key={id} href={`#/${id}`} className={route === id ? 'selected' : ''} aria-current={route === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon name={icon} /><span>{label}</span>{id === 'approvals' && <b className="nav-count">1</b>}</a>)}</nav>
      <div className="sidebar-bottom"><span className="status-dot" />Локальный просмотр<small>Рабочая система не подключена</small></div>
      <div className="profile"><span className="avatar">{role === 'manager' ? 'А' : 'Р'}</span><div><strong>{role === 'manager' ? managers[0].name : 'Руководитель (демо)'}</strong><small>{role === 'manager' ? 'Менеджер' : 'Руководитель'}</small></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><span>Рабочее пространство <span className="crumb">/ {title}</span></span><div><span className="top-date">21 октября 2026 · среда</span><span className="avatar small">{role === 'manager' ? 'А' : 'Р'}</span></div></header>
      <main className="page-content"><div className="demo-banner"><span><b>ДЕМО</b> Все сотрудники, планы и результаты вымышлены. API и CRM не подключены.</span><label>Просмотр роли<select aria-label="Демонстрационная роль" value={role} onChange={e => switchRole(e.target.value as Role)}><option value="manager">Менеджер</option><option value="supervisor">Руководитель</option></select></label></div>
        <div className="page-heading"><div><p className="eyebrow">{role === 'manager' ? 'ВАШ РАБОЧИЙ ДЕНЬ' : 'КОМАНДА И РЕЗУЛЬТАТЫ'}</p><h1>{title}</h1><p className="muted">{role === 'manager' ? 'Всё важное — в одном месте. Сосредоточьтесь на следующем шаге.' : 'Планы, нагрузка и прогресс сотрудников без лишнего шума.'}</p></div>
          {role === 'supervisor' && <label className="employee-filter">Сотрудник<select aria-label="Сотрудник" value={employee} onChange={e => setEmployee(e.target.value)}><option value="all">Весь отдел</option>{managers.map(m => <option value={m.id} key={m.id}>{m.name}</option>)}</select></label>}
          {route === 'home' && <button className="button secondary" onClick={() => navigate('plan')}><Icon name="plan" />Открыть планы <span>↗</span></button>}
        </div>
        {route === 'home' && <>
          <div className="stats-grid">{role === 'manager' ? <>
            <Stat title="Задачи на сегодня" value={String(items.length)} hint="Из демонстрационного плана" icon="tasks" />
            <Stat title="Завершено задач" value={`${done} из ${items.length}`} hint="Прогресс текущего дня" tone="green" icon="approvals" />
            <Stat title="Плановое время" value={`${plan.summary.planned_minutes} мин`} hint="Сумма плановых интервалов" tone="orange" icon="plan" />
            <Stat title="Фактическое время" value={duration(plan.summary.actual_seconds)} hint="Снимок серверного состояния" tone="violet" icon="history" />
          </> : <>
            <Stat title="Сотрудники" value={String(scoped.length)} hint={employee === 'all' ? 'Два активных демо-менеджера' : 'Данные выбранного сотрудника'} icon="employees" />
            <Stat title="Подтверждённые планы" value={String(scoped.filter(p => p.status === 'approved').length)} hint="В выбранной области просмотра" tone="green" icon="approvals" />
            <Stat title="Выполнено задач" value={`${done} из ${items.length}`} hint="Без объединения CRM-метрик" tone="orange" icon="tasks" />
            <Stat title="Требует согласования" value={employee === 'all' || employee === '102' ? '1' : '0'} hint="Вымышленный запрос изменения" tone="violet" icon="plan" />
          </>}</div>
          {role === 'manager' ? <div className="dashboard-grid"><section className="card current-card"><div className="section-heading"><h2>Текущая задача</h2><span className="live-label"><i />В работе</span></div><p className="eyebrow">ИЗ ПЛАНА НА СЕГОДНЯ</p><h3>{current?.title || 'Активной задачи нет'}</h3><p className="muted">Утреннее распределение · 19–20 октября · 12 лидов</p><div className="current-main"><div className="timer">{current ? duration(current.elapsed_seconds) : '—'}<small>снимок серверного таймера</small></div><div className="current-target"><strong>5<span> / 12</span></strong><small>тестовый факт / назначено</small></div></div><div className="current-actions"><button className="button" disabled title="Серверные действия будут доступны после авторизации">Ⅱ Пауза</button><button className="button secondary" onClick={() => navigate('tasks')}>К задаче →</button><span>Изменения не отправляются</span></div></section><PlanCard plan={plan} /></div>
            : <section className="card"><div className="section-heading"><h2>{employee === 'all' ? 'Команда сегодня' : 'Выбранный сотрудник'}</h2><span className="badge">Демо-снимок</span></div><div className="employee-grid">{scoped.map(p => <article className="employee-card" key={p.id}><div className="employee-top"><span className="avatar">{p.employee_name[0]}</span><div><h3>{p.employee_name}</h3><small>Менеджер · 21 октября</small></div><span className={`badge ${p.status}`}>{planStatus[p.status]}</span></div><div className="employee-numbers"><div><strong>{p.summary.done} / {p.summary.total}</strong><small>задач завершено</small></div><div><strong>{duration(p.summary.actual_seconds)}</strong><small>фактическое время</small></div></div><Progress value={Math.round(p.summary.done / p.summary.total * 100)} /><button className="text-button" onClick={() => { setEmployee(String(p.employee_id)); navigate('plan'); }}>Посмотреть план →</button></article>)}</div></section>}
          <section className="card today-tasks"><div className="section-heading"><div><h2>Задачи на сегодня</h2><p className="muted">{role === 'manager' ? 'Ближайшие шаги вашего дня' : 'Краткий срез выбранных планов'}</p></div><button className="text-button" onClick={() => navigate('tasks')}>Все задачи →</button></div><TaskRows items={items.slice(0, 3)} showEmployee={role === 'supervisor' && employee === 'all'} /></section>
          <section className="metrics-prompt"><span className="icon-tile blue"><Icon name="metrics" /></span><div><h3>Картина шире одного дня</h3><p>Показатели звонков и консультаций — в отдельном разделе.</p></div><button className="text-button" onClick={() => navigate('metrics')}>Перейти к показателям →</button></section>
        </>}
        {route === 'metrics' && <><div className="metric-toolbar"><div className="segmented" role="group" aria-label="Период показателей">{([['day', 'Сегодня'], ['week', 'Неделя'], ['month', 'Месяц']] as const).map(([value, label]) => <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{label}</button>)}</div><label>Дата периода<input aria-label="Дата периода" type="date" value={metricDay} onChange={e => e.target.value && setMetricDay(e.target.value)} /></label><span className="scope-label">{role === 'manager' ? 'Мои показатели' : employee === 'all' ? 'Отдел · личные нормы не суммируются' : plan.employee_name}</span></div><div className="notice">Нормы из задания владельца действуют с 01.11.2026. Расчёт адаптации новичков и пересчёт периодов пока не настроены.</div><div className="metric-grid">{metrics.map((m, index) => <article className="card metric-card" key={m.key}><div className="section-heading"><span className={`icon-tile ${index % 2 ? 'green' : 'blue'}`}><Icon name="metrics" /></span><span className="badge">Не подключено</span></div><h2>{m.name}</h2><p className="muted">{m.description}</p><div className="metric-no-data">Нет данных</div><p className="metric-norm">{role === 'supervisor' && employee === 'all' ? `Личная норма с 01.11: ${m.norm} ${m.unit} / ${m.period === 'unspecified' ? 'период требует уточнения' : m.period === 'day' ? 'день' : 'неделю'} · итог отдела не задан` : normLabel(m, metricDay, period)}</p><div className="empty-progress" /><small>Прогресс недоступен · интеграция ещё не подключена</small><div className="metric-source">{m.source}<br />Обновление: нет данных</div></article>)}</div></>}
        {route === 'plan' && <div className="plan-page">{scoped.map(p => <div key={p.id}><PlanCard plan={p} /><section className="card"><div className="section-heading"><h2>Состав плана · {p.employee_name}</h2><span className="badge">Только просмотр</span></div><TaskRows items={p.tasks} /><div className="notice">Количество из распределения защищено. Подтверждение плана и согласование целей будут использовать существующие серверные правила после подключения web-входа.</div></section></div>)}</div>}
        {route === 'tasks' && <section className="card"><div className="section-heading"><h2>Задачи и прогресс</h2><span className="badge">{items.length} задач · демо</span></div><TaskRows items={items} showEmployee={role === 'supervisor' && employee === 'all'} /></section>}
        {route === 'employees' && role === 'supervisor' && <section className="card"><h2>Сотрудники отдела</h2><div className="employee-grid">{managers.map(m => <article className="employee-card" key={m.id}><span className="avatar">{m.name[0]}</span><h3>{m.name}</h3><p className="muted">Активный менеджер · вымышленная запись</p><button className="text-button" onClick={() => { setEmployee(String(m.id)); navigate('plan'); }}>Открыть план →</button></article>)}</div></section>}
        {route === 'approvals' && role === 'supervisor' && <section className="card"><div className="section-heading"><h2>Запросы на согласование</h2><span className="badge">Демонстрация</span></div>{employee === 'all' || employee === '102' ? <article className="approval-card"><span className="badge draft">Ожидает решения</span><h3>Изменение планового времени</h3><p>Мария (демо) · подготовить предложение · 45 → 60 минут</p><p className="muted">Вымышленная причина: требуется дополнительная подготовка.</p><button className="button" disabled>Согласовать</button><small>Решения не отправляются: авторизация не подключена</small></article> : <Empty title="Запросов нет" text="Для выбранного демонстрационного сотрудника нет запросов." />}</section>}
        {(route === 'active-calls' || route === 'closed-calls') && <Empty title={title} text="В разработке. Клиенты, телефония и отдельная таблица обзвона не подключены." />}
        {route === 'history' && <Empty title="История" text="Архивные планы и события не загружены. Визуальный прототип не читает рабочую базу." />}
        {route === 'reports' && <Empty title="Отчёты" text="Закрытые отчёты не загружены. Существующая история сохраняется на backend." />}
        {route === 'settings' && <Empty title="Настройки" text="Тёмная тема. Управление настоящей учётной записью будет доступно после защищённого входа." />}
        <footer className="page-footer"><span>План дня · desktop-прототип</span><span>Демо-снимок: {snapshotTime} · без подключения к Telegram</span></footer>
      </main>
    </div>
  </div>;
}
function Empty({ title, text }: { title: string; text: string }) { return <section className="card empty-state"><span className="empty-symbol"><Icon name="plan" /></span><p className="eyebrow">РАЗДЕЛ ГОТОВИТСЯ</p><h2>{title}</h2><p>{text}</p></section>; }
