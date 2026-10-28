import { Plus, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'wouter'
import { useAuth } from '../auth/AuthContext'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { Lead, LeadList, Source } from '../types'
import { Modal } from '../components/WorkspaceUI'

export function LeadsPage() {
  const { user } = useAuth()
  const [data, setData] = useState<LeadList | null>(null)
  const [query, setQuery] = useState('')
  const [sources, setSources] = useState<Source[]>([])
  const [modal, setModal] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const failed = (reason: unknown) => setError(reason instanceof Error ? reason.message : 'Не удалось загрузить лиды')
  const load = () => api<LeadList>('/leads?page_size=100').then(setData).catch(failed)
  useEffect(() => {
    const controller = new AbortController()
    const rejected = (reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить лиды') }
    api<LeadList>('/leads?page_size=100', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setData(value) }).catch(rejected)
    api<Source[]>('/sources', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setSources(value) }).catch(rejected)
    return () => controller.abort()
  }, [user?.role, reload])
  const filtered = useMemo(() => data?.items.filter(l => `${l.name} ${l.phone} ${l.comment}`.toLowerCase().includes(query.toLowerCase())) || [], [data, query])
  return <>
    <PageHeader title="Лиды" subtitle={data ? `${data.total} обращений в системе` : error ? 'Данные недоступны' : 'Загрузка лидов…'} action={user?.role !== 'manager' && <button className="button button-primary" onClick={() => setModal(true)}><Plus size={18} />Добавить лид</button>} />
    {error && <div role="alert" className="alert">{error}<button onClick={() => { setError(''); setReload(value => value + 1) }}>Повторить загрузку лидов</button></div>}
    {notice && <div className="success-alert">{notice}</div>}
    <section className="panel"><div className="toolbar"><div className="search"><Search size={18} /><input placeholder="Имя, телефон или комментарий" value={query} onChange={e => setQuery(e.target.value)} /></div></div>
      {!data ? (!error && <p className="table-empty" role="status">Загрузка лидов…</p>) : filtered.length ? <div className="table-wrap"><table><thead><tr><th>Контакт</th><th>Комментарий</th><th>Менеджер</th><th>Создан</th><th>Статус</th></tr></thead><tbody>{filtered.map(lead => <tr key={lead.id}>
        <td><Link className="lead-name" href={`/leads/${lead.id}`}>{lead.name || 'Без имени'}</Link><small>{lead.phone}</small></td><td className="comment-cell">{lead.comment || '—'}</td><td>{lead.manager?.full_name || <span className="muted">Не назначен</span>}</td><td>{dateTime(lead.created_at)}</td><td><StatusBadge status={lead.sync_status} /></td>
      </tr>)}</tbody></table></div> : <EmptyState text="Добавьте первый лид, чтобы начать распределение" />}
    </section>
    {modal && <LeadModal sources={sources} onClose={() => setModal(false)} onCreated={lead => { setModal(false); setNotice(import.meta.env.VITE_LOCAL_PLANNER_MVP === '1' ? `Лид назначен локально: ${lead.manager?.full_name}. CRM не изменялась.` : `Лид распределён: ${lead.manager?.full_name}. Отправка в Bitrix24 поставлена в очередь.`); load() }} />}
  </>
}

function LeadModal({ sources, onClose, onCreated }: { sources: Source[]; onClose(): void; onCreated(lead: Lead): void }) {
  const [requestId] = useState(() => crypto.randomUUID())
  const [form, setForm] = useState({ phone: '', name: '', comment: '', source: sources[0]?.external_id || '' })
  const [error, setError] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError('')
    try { const lead = await api<Lead>(import.meta.env.VITE_LOCAL_PLANNER_MVP === '1' ? '/local-leads' : '/leads', { method: 'POST', body: JSON.stringify(import.meta.env.VITE_LOCAL_PLANNER_MVP === '1' ? { request_id: requestId, lead: { ...form, auto_assign: true } } : { ...form, auto_assign: true }) }); onCreated(lead) }
    catch (err) { setError(err instanceof Error ? err.message : 'Ошибка') }
  }
  return <Modal label="Новый лид" onClose={onClose}><form className="modal" onSubmit={submit}><div className="modal-head"><div><h2>Новый лид</h2><p>Добавьте входящее обращение вручную</p></div><button type="button" onClick={onClose}><X /></button></div>
    <div className="form-grid"><label>Телефон *<input value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} placeholder="+7 999 000-00-00" required autoFocus /></label><label>Имя<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Имя клиента" /></label><label className="span-2">Источник<select required value={form.source} onChange={e => setForm({ ...form, source: e.target.value })}><option value="" disabled>{sources.length ? 'Выберите источник' : 'Источники синхронизируются…'}</option>{sources.map(source => <option key={source.external_id} value={source.external_id}>{source.name}</option>)}</select></label><label className="span-2">Комментарий<textarea value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} placeholder="Что важно знать о запросе" /></label></div>
    <p className="distribution-hint">{import.meta.env.VITE_LOCAL_PLANNER_MVP === '1' ? 'Локальное назначение по существующему алгоритму LeadFlow. Bitrix24 и Telegram не изменяются.' : 'После сохранения лид автоматически получит доступного менеджера и будет создан в Bitrix24.'}</p>{error && <div className="alert">{error}</div>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose}>Отмена</button><button disabled={!sources.length} className="button button-primary">Готово</button></div>
  </form></Modal>
}
