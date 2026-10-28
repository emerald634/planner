import { ArrowLeft, BriefcaseBusiness, CalendarDays, MessageSquareText, Phone, UserRound } from 'lucide-react'
import { Link, useRoute } from 'wouter'
import { useAuth } from '../auth/AuthContext'
import { LocalLeadAssignment } from '../components/LocalLeadAssignment'
import { StatusBadge } from '../components/StatusBadge'
import { useResource } from '../lib/useResource'
import { ErrorState, LoadingState } from '../components/WorkspaceUI'
import { dateTime } from '../lib/format'
import type { Lead, Source } from '../types'

export function LeadDetailPage() {
  const { user } = useAuth()
  const [, params] = useRoute('/leads/:id'); const id = params?.id
  const resource = useResource<Lead>(`/leads/${id}`)
  const sources = useResource<Source[]>('/sources')
  const lead = resource.data
  if (resource.error) return <ErrorState title="Карточка лида недоступна" message={resource.error} retry={resource.retry} />
  if (!lead) return <LoadingState text="Загрузка карточки лида…" />
  const sourceName = sources.data?.find(s => s.external_id === lead.source)?.name || lead.source
  return <>
    <Link href="/leads" className="back-link"><ArrowLeft size={17} />К списку лидов</Link>
    {sources.error && <ErrorState title="Название источника недоступно" message={sources.error} retry={sources.retry} />}
    <header className="detail-header"><div><span className="eyebrow">ЛИД #{lead.id}</span><h1>{lead.name || 'Без имени'}</h1><div className="phone-row"><a href={`tel:${lead.phone}`}><Phone size={17} />{lead.phone}</a><span className={`badge badge-${lead.bitrix_deal_id ? 'deal' : 'lead'}`}><i />{lead.bitrix_deal_id ? 'Сделка' : 'Лид'}</span></div></div><StatusBadge status={lead.sync_status} /></header>
    <div className="detail-grid"><section className="panel detail-main"><h2>Информация о лиде</h2><dl><div><dt><MessageSquareText size={18} />Комментарий</dt><dd>{lead.comment || 'Комментарий не указан'}</dd></div><div><dt><UserRound size={18} />Ответственный</dt><dd>{lead.manager?.full_name || 'Не назначен'}</dd></div><div><dt><CalendarDays size={18} />Создан</dt><dd>{dateTime(lead.created_at)}</dd></div><div><dt><BriefcaseBusiness size={18} />Источник</dt><dd>{sourceName}</dd></div></dl></section>
      <aside className="panel crm-panel"><h2>Bitrix24</h2><div className="crm-row"><span>Lead ID</span><strong>{lead.bitrix_lead_id || '—'}</strong></div><div className="crm-row"><span>Стадия лида</span><strong>{lead.bitrix_lead_status_name || '—'}</strong></div><div className="crm-row"><span>Deal ID</span><strong>{lead.bitrix_deal_id || '—'}</strong></div><div className="crm-row"><span>Стадия сделки</span><strong>{lead.bitrix_deal_stage_name || '—'}</strong></div><div className="crm-row"><span>Проверено</span><strong>{dateTime(lead.last_crm_sync_at)}</strong></div><div className="crm-timeline"><span>Перемещения</span>{lead.crm_events.length ? lead.crm_events.map((event, index) => <div className="crm-event" key={`${event.entity_type}-${event.stage_id}-${index}`}><i /><div><strong>{event.entity_type === 'lead' ? 'Лид' : 'Сделка'} · {event.stage_name || event.stage_id}</strong><small>{dateTime(event.moved_at || event.created_at)}</small></div></div>) : <p>Стадии появятся после первой синхронизации.</p>}</div></aside>
    </div>
    {user?.role !== 'manager' && <LocalLeadAssignment leadId={lead.id} refreshed={resource.retry} />}
  </>
}
