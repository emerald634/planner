import { CalendarClock, Plus, Trash2, UserRound, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { api } from '../lib/api'
import { roleLabels } from '../lib/format'
import type { Role, User } from '../types'
import { ErrorState, LoadingState, Modal } from '../components/WorkspaceUI'
import { useResource } from '../lib/useResource'

const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export function ManagersPage({ embedded = false }: { embedded?: boolean }) {
  const { user: actor } = useAuth()
  const resource = useResource<User[]>('/users')
  const users = resource.data
  const [mutationError, setMutationError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const load = resource.retry
  const remove = async (user: User) => {
    if (confirm(`Удалить пользователя «${user.full_name}»?`)) {
      try { await api(`/users/${user.id}`, { method: 'DELETE' }); load() }
      catch (error) { setMutationError(error instanceof Error ? error.message : 'Не удалось удалить пользователя.') }
    }
  }
  return <>
    {!embedded && <PageHeader title="Команда" subtitle="Графики, выходные и доступность менеджеров" />}
    {actor?.role === 'admin' && <div className="ui-section-actions"><button className="button button-primary" onClick={() => setCreateOpen(true)}><Plus size={18} />Добавить</button></div>}
    {resource.loading && <LoadingState text="Загрузка учётных записей…" />}
    {resource.error && <ErrorState title="Учётные записи недоступны" message={resource.error} retry={load} />}
    {mutationError && <ErrorState title="Изменение не выполнено" message={mutationError} />}
    {users?.length ? <div className="people-grid">{users.map(user => <article className="person-card" key={user.id}>
      <div className="person-top"><span className="person-avatar"><UserRound /></span><span className={user.is_active ? 'online-dot' : 'offline-dot'} /></div>
      <h3>{user.full_name}</h3><p>{user.email}</p>
      <div className="person-meta"><span>{roleLabels[user.role]}</span><span>{user.is_active ? 'Активен' : 'Отключён'}</span></div>
      {user.role === 'manager' && <div className="schedule-summary"><CalendarClock size={15} /><span>{user.work_days.map(day => dayNames[day]).join(', ')} · {user.workday_start.slice(0, 5)}–{user.workday_end.slice(0, 5)}{user.unavailable_until ? ` · выходной до ${user.unavailable_until}` : ''}</span></div>}
      <div className="integration-tags"><span className={user.bitrix_user_id ? 'connected' : ''}>Bitrix24</span><span className={user.telegram_chat_id ? 'connected' : ''}>Telegram</span></div>
      {actor?.role === 'admin' && <div className="card-actions">{user.role === 'manager' && <button className="button button-secondary" onClick={() => setEditing(user)}>Редактировать</button>}{actor.id !== user.id && <button className="card-delete" onClick={() => remove(user)} title="Удалить"><Trash2 size={16} /></button>}</div>}
    </article>)}</div> : users && <EmptyState text="Добавьте сотрудников отдела продаж" />}
    {createOpen && <UserModal onClose={() => setCreateOpen(false)} onCreated={() => { setCreateOpen(false); void load() }} />}
    {editing && <ScheduleModal user={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load() }} />}
  </>
}

function DayPicker({ value, onChange }: { value: number[]; onChange(value: number[]): void }) {
  const toggle = (day: number) => onChange(value.includes(day) ? value.filter(item => item !== day) : [...value, day].sort())
  return <div className="day-picker">{dayNames.map((name, day) => <button type="button" className={value.includes(day) ? 'selected' : ''} onClick={() => toggle(day)} key={name}>{name}</button>)}</div>
}

function ScheduleModal({ user, onClose, onSaved }: { user: User; onClose(): void; onSaved(): void }) {
  const [form, setForm] = useState({ work_days: user.work_days, workday_start: user.workday_start.slice(0, 5), workday_end: user.workday_end.slice(0, 5), unavailable_until: user.unavailable_until || '', bitrix_user_id: user.bitrix_user_id || '', telegram_chat_id: user.telegram_chat_id || '' })
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    if (!form.work_days.length) { setError('Выберите хотя бы один рабочий день'); return }
    try { await api(`/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ ...form, unavailable_until: form.unavailable_until || null, bitrix_user_id: form.bitrix_user_id || null, telegram_chat_id: form.telegram_chat_id || null }) }); onSaved() }
    catch (err) { setError(err instanceof Error ? err.message : 'Ошибка') }
  }
  return <Modal label="Редактирование менеджера" onClose={onClose}><form className="modal" onSubmit={submit}>
    <div className="modal-head"><div><h2>Редактирование менеджера</h2><p>{user.full_name}</p></div><button type="button" onClick={onClose}><X /></button></div>
    <div className="form-grid"><label className="span-2">Bitrix User ID<input value={form.bitrix_user_id} onChange={event => setForm({ ...form, bitrix_user_id: event.target.value })} placeholder="Например, 24" /><small>Нужен, чтобы назначить этого менеджера ответственным в CRM.</small></label><label className="span-2">Telegram Chat ID<input value={form.telegram_chat_id} onChange={event => setForm({ ...form, telegram_chat_id: event.target.value })} placeholder="Например, 123456789" /><small>Нужен, чтобы менеджер получал уведомления о новых лидах в Telegram.</small></label><label className="span-2">Рабочие дни<DayPicker value={form.work_days} onChange={work_days => setForm({ ...form, work_days })} /></label><label>Начало смены<input required type="time" value={form.workday_start} onChange={event => setForm({ ...form, workday_start: event.target.value })} /></label><label>Конец смены<input required type="time" value={form.workday_end} onChange={event => setForm({ ...form, workday_end: event.target.value })} /></label><label className="span-2">Выходной / отпуск до<input type="date" value={form.unavailable_until} onChange={event => setForm({ ...form, unavailable_until: event.target.value })} /><small>Оставьте пустым, если менеджер доступен по обычному графику.</small></label></div>
    {error && <div className="alert">{error}</div>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose}>Отмена</button><button className="button button-primary">Сохранить</button></div>
  </form></Modal>
}

function UserModal({ onClose, onCreated }: { onClose(): void; onCreated(): void }) {
  const [form, setForm] = useState({ full_name: '', email: '', password: '', role: 'manager' as Role, telegram_chat_id: '', bitrix_user_id: '', work_days: [0, 1, 2, 3, 4], workday_start: '09:00', workday_end: '18:00' })
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    try { await api('/users', { method: 'POST', body: JSON.stringify({ ...form, telegram_chat_id: form.telegram_chat_id || null, bitrix_user_id: form.bitrix_user_id || null }) }); onCreated() }
    catch (err) { setError(err instanceof Error ? err.message : 'Ошибка') }
  }
  return <Modal label="Новый пользователь" onClose={onClose}><form className="modal" onSubmit={submit}>
    <div className="modal-head"><div><h2>Новый пользователь</h2><p>Создайте учётную запись сотрудника</p></div><button type="button" onClick={onClose}><X /></button></div>
    <div className="form-grid"><label>Имя *<input required value={form.full_name} onChange={event => setForm({ ...form, full_name: event.target.value })} /></label><label>Email *<input required type="email" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label><label>Пароль *<input required minLength={8} type="password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} /></label><label>Роль<select value={form.role} onChange={event => setForm({ ...form, role: event.target.value as Role })}><option value="manager">Менеджер</option><option value="supervisor">Руководитель</option><option value="admin">Администратор</option></select></label><label>Telegram Chat ID<input value={form.telegram_chat_id} onChange={event => setForm({ ...form, telegram_chat_id: event.target.value })} /></label><label>Bitrix User ID<input value={form.bitrix_user_id} onChange={event => setForm({ ...form, bitrix_user_id: event.target.value })} /></label>{form.role === 'manager' && <label className="span-2">Рабочие дни<DayPicker value={form.work_days} onChange={work_days => setForm({ ...form, work_days })} /></label>}</div>
    {error && <div className="alert">{error}</div>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose}>Отмена</button><button className="button button-primary">Создать</button></div>
  </form></Modal>
}
