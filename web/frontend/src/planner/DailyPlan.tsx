import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Plan } from './transport'

type Attempt = { id: string; time: string; call: boolean; message: boolean; connected: boolean; result: string }
type Detail = { id: string; client: string; entity_id: number | null; group: 'active' | 'completed' | ''; done: boolean; recommendation: boolean; payment_date: string | null; touch_date: string | null; result: string; attempts: Attempt[]; created_date?: string }
type Indicator = { key: string; label: string; planned: number; actual: number; morning: number; connected?: number; remaining: number; source: string; details: Detail[] }
export type Daily = { revision: number; updated_at: number | null; contracts: number; indicators: Indicator[] }
type Weekly = { start: string; days: string[]; totals: Record<string, number>; targets: Record<string, number>; consultations_stretch: number }
type Source = { key:string;name:string;status:string;updated_at:number;error?:string;items:Record<string,unknown>[]|null }

export function validateDaily(value: unknown): asserts value is Daily {
  if (!value || typeof value !== 'object') throw new Error('Некорректный ответ показателей')
  const d = value as Daily
  const keys = ['calls','new_leads','missed','consultations','pain','conversations','overdue','payments']
  if (!Number.isInteger(d.revision) || d.revision < 0 || !Number.isInteger(d.contracts) || !Array.isArray(d.indicators) || d.indicators.length !== 8 || new Set(d.indicators.map(r => r.key)).size !== 8 || !d.indicators.every(r => keys.includes(r.key) && typeof r.label === 'string' && typeof r.source === 'string' && [r.planned,r.actual,r.morning,r.remaining].every(v => Number.isFinite(v) && v >= 0) && Array.isArray(r.details) && r.details.every(x => typeof x.id === 'string' && typeof x.client === 'string' && Array.isArray(x.attempts)))) throw new Error('Некорректный ответ показателей. Повторите загрузку.')
}
const text = (e: unknown) => e instanceof Error ? e.message : 'Не удалось загрузить показатели'
const blank = (): Detail => ({ id: crypto.randomUUID(), client: '', entity_id: null, group: '', done: false, recommendation: false, payment_date: null, touch_date: null, result: '', attempts: [] })

export function DailyPlan({ plan, snapshot, onDirtyChange }: { plan: Plan; snapshot?: Daily; onDirtyChange?: (dirty:boolean)=>void }) {
  const [data, setData] = useState<Daily | undefined>(snapshot)
  const [weekly, setWeekly] = useState<Weekly>()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [weeklyError, setWeeklyError] = useState('')
  const [sources,setSources]=useState<Source[]>()
  const [sourceError,setSourceError]=useState('')
  const [sourceReload,setSourceReload]=useState(0)
  useEffect(()=>{
    if(snapshot || plan.status === 'closed')return
    const c=new AbortController()
    const kinds = ['leads','deals','tasks','calls']
    kinds.forEach(kind => {
      api<Source>(`/planner/plans/${plan.id}/sources/${kind}`,{method:'POST',signal:c.signal}).then(row=>{
        if (!row || row.key !== kind || typeof row.name !== 'string' || !['verified','unavailable'].includes(row.status) || (row.items!==null&&!Array.isArray(row.items))) throw new Error('Ошибка формата источника')
        if(!c.signal.aborted)setSources(old=>[...(old||[]).filter(x=>x.key!==kind),row])
      }).catch(e=>{if(!c.signal.aborted)setSources(old=>[...(old||[]).filter(x=>x.key!==kind),{key:kind,name:kind,status:'unavailable',updated_at:Date.now()/1000,items:null,error:text(e)}])})
    })
    return()=>c.abort()
  },[plan.id,plan.status,snapshot,sourceReload])
  useEffect(() => {
    if (snapshot) return
    const controller = new AbortController()
    api<unknown>(`/planner/plans/${plan.id}/daily`, { signal: controller.signal }).then(value => { validateDaily(value); if (!controller.signal.aborted) {setData(value);onDirtyChange?.(false)} }).catch(e => { if (!controller.signal.aborted) setError(text(e)) })
    return () => controller.abort()
  }, [plan.id, reload, snapshot, onDirtyChange])
  useEffect(() => {
    const controller = new AbortController()
    api<Weekly>(`/planner/weekly?employee_id=${plan.employee_id}&day=${plan.day}`, { signal: controller.signal }).then(value => { if (!value || typeof value.start !== 'string' || !value.totals || !value.targets || !Array.isArray(value.days)) throw new Error('Ошибка формата недельной сводки'); if (!controller.signal.aborted) setWeekly(value) }).catch(e => { if (!controller.signal.aborted) setWeeklyError(text(e)) })
    return () => controller.abort()
  }, [plan.employee_id, plan.day, reload])
  const closed = plan.status === 'closed' || !!snapshot
  function edit(index: number, patch: Partial<Indicator>) { onDirtyChange?.(true); if (data) setData({ ...data, indicators: data.indicators.map((r,i) => i === index ? { ...r, ...patch } : r) }) }
  function detail(index: number, n: number, patch: Partial<Detail>) {
    if (!data) return
    const row = data.indicators[index]
    const details = row.details.map((x,i) => i === n ? { ...x, ...patch } : x)
    edit(index, { details, ...(['consultations','conversations'].includes(row.key) ? { actual: details.filter(x => x.done).length } : {}) })
  }
  async function save() {
    if (!data) return
    setBusy(true); setError(''); setNotice('')
    try {
      const indicators = data.indicators.map(({ key, planned, actual, morning, details }) => ({ key, planned, actual, morning, details: details.map(x => ({ id: x.id, client: x.client, entity_id: x.entity_id, group: x.group || '', done: x.done || false, recommendation: x.recommendation || false, payment_date: x.payment_date || null, touch_date: x.touch_date || null, result: x.result || '', attempts: x.attempts })) }))
      const result = await api<unknown>(`/planner/plans/${plan.id}/daily`, { method: 'PUT', body: JSON.stringify({ revision: data.revision, contracts: data.contracts, indicators }) })
      validateDaily(result); setData(result); onDirtyChange?.(false); setNotice('Показатели сохранены на сервере'); setReload(x => x + 1)
    } catch (e) { setError(text(e)) } finally { setBusy(false) }
  }
  return <section className="pw-card daily-plan"><div className="pw-section-heading"><div><h2>Дневные показатели · план / факт</h2><p>Восемь показателей · {plan.day} · {plan.employee_name}</p></div>{!closed && <button disabled={busy || !data} onClick={save}>Сохранить показатели</button>}</div>
    {error && <div role="alert" className="pw-error">{error}<button onClick={() => { setError(''); setReload(x => x+1) }}>Обновить показатели с сервера</button><small>Обновление заменит несохранённые поля. При неизвестном исходе сохранения сначала обновите данные.</small></div>}
    {notice && <p role="status">{notice}</p>}{!data && !error && <p role="status">Загрузка показателей…</p>}
    {!closed&&<details><summary>Источники Bitrix24 (не заменяют ручные результаты)</summary>{sourceError&&<p role="alert">{sourceError}</p>}{!sources&&!sourceError&&<p role="status">Проверка источников…</p>}{sources?.map(s=><div className="pw-history" key={s.key}><strong>{s.name}: {s.status==='verified'?'Проверено':'Недоступно'}</strong><p>{s.error||`Получено ${s.items?.length} записей. Это не доказывает обработку/качество/заполнение боли/оплату.`}</p><small>{new Date(s.updated_at*1000).toLocaleString('ru-RU')}</small>{s.items?.slice(0,100).map((x,i)=><p key={i}>{String(x.title||x.TITLE||'Запись')} · ID {String(x.id||x.ID||x.CALL_ID)}</p>)}</div>)}<button onClick={()=>{setSourceError('');setSourceReload(x=>x+1)}}>Повторить проверку источников</button><p>Доступность источников проверяется отдельно. Ручной факт сохраняется при ошибке CRM.</p></details>}
    {data && <><p className="pw-muted">Источник: ручной ввод, кроме исходного списка недозвонов. После подтверждения собственные ручные списки можно увеличивать; снижение — решением руководителя. Обновлено: {data.updated_at ? new Date(data.updated_at*1000).toLocaleString('ru-RU') : 'ещё не сохранялось'}. Консультации: норма2, дополнительная цель3.</p>
    {data.indicators.map((row,index) => <article key={row.key} className="pw-history" data-indicator={row.key}><h3>{index+1}. {row.label}</h3><fieldset disabled={closed || busy}><div className="pw-fields"><label>План<input aria-label={`План ${row.label}`} type="number" min="0" max="1000000" value={row.planned} disabled={['calls','consultations','conversations','overdue','missed'].includes(row.key)} onChange={e => edit(index,{planned:Number(e.target.value)})}/></label><label>{row.key === 'overdue' ? 'Вечерний остаток' : 'Факт'}<input aria-label={`Факт ${row.label}`} type="number" min="0" max="1000000" value={row.actual} disabled={['missed','consultations','conversations'].includes(row.key)} onChange={e => edit(index,{actual:Number(e.target.value)})}/></label>{row.key === 'overdue' && <label>Утро<input aria-label="Просроченные утром" type="number" min="0" value={row.morning} onChange={e => edit(index,{morning:Number(e.target.value)})}/></label>}</div>
    <p>{row.key === 'overdue' ? `Цель: 0 к концу дня; при накоплении сокращать минимум на10, пока не станет0. Сокращено: ${Math.max(0,row.morning-row.actual)}.` : `${Math.min(100,Math.round(row.actual/Math.max(1,row.planned)*100))}% · осталось ${Math.max(0,row.planned-row.actual)}`}{row.key === 'payments' && ' · Касания: за1–2 дня до ожидаемой оплаты и в день оплаты; получение оплаты автоматически не подтверждается.'}{row.key === 'missed' && ` · Дозвонились: ${row.connected || 0}. Норма: звонок И сообщение.`}</p><small>{row.source}</small>
    <details><summary>Детали клиентов / попытки ({row.details.length})</summary>{row.details.map((d,n) => <div className="pw-request" key={d.id}><div className="pw-fields"><label>Клиент<input aria-label="Клиент показателя" value={d.client} maxLength={180} disabled={row.key === 'missed'} onChange={e => detail(index,n,{client:e.target.value})}/></label>{row.key === 'missed' && <span>CRM ID {d.entity_id} · {d.created_date}</span>}{row.key === 'conversations' && <label>Группа<select value={d.group} onChange={e => detail(index,n,{group:e.target.value as Detail['group']})}><option value="">Выберите</option><option value="active">Действующий</option><option value="completed">Завершённый</option></select></label>}{row.key !== 'missed' && <label><input type="checkbox" checked={d.done} onChange={e => detail(index,n,{done:e.target.checked})}/>Выполнено / состоялось</label>}{row.key === 'conversations' && <label><input type="checkbox" checked={d.recommendation} onChange={e => detail(index,n,{recommendation:e.target.checked})}/>Есть рекомендация</label>}{row.key === 'payments' && <><label>Дата ожидаемой оплаты<input type="date" value={d.payment_date || ''} onChange={e => detail(index,n,{payment_date:e.target.value || null})}/></label><label>Касание запланировано<input type="date" value={d.touch_date || ''} onChange={e => detail(index,n,{touch_date:e.target.value || null})}/></label></>}</div><label>Результат<textarea value={d.result} maxLength={2000} onChange={e => detail(index,n,{result:e.target.value})}/></label>
    {row.key === 'missed' && <>{d.attempts.map((a,k) => <div key={a.id} className="pw-fields"><label>Время попытки<input type="time" value={a.time} onChange={e => detail(index,n,{attempts:d.attempts.map((x,j)=> j===k ? {...x,time:e.target.value}:x)})}/></label>{(['call','message','connected'] as const).map(field => <label key={field}><input type="checkbox" checked={a[field]} onChange={e=>detail(index,n,{attempts:d.attempts.map((x,j)=>j===k?{...x,[field]:e.target.checked}:x)})}/>{{call:'Звонок',message:'Сообщение (ручная отметка)',connected:'Дозвонились'}[field]}</label>)}</div>)}<button type="button" onClick={()=>detail(index,n,{attempts:[...d.attempts,{id:crypto.randomUUID(),time:'10:00',call:false,message:false,connected:false,result:''}]})}>Добавить повторную попытку</button></>}
    </div>)}{row.key !== 'missed' && <button type="button" onClick={()=>edit(index,{details:[...row.details,blank()]})}>Добавить клиента</button>}</details></fieldset></article>)}
    <label>Договоры за выбранный день (для недельного итога)<input aria-label="Договоры для недели" disabled={closed || busy} type="number" min="0" value={data.contracts} onChange={e=>{onDirtyChange?.(true);setData({...data,contracts:Number(e.target.value)})}}/></label></>}
    {weeklyError && <p role="alert">Недельная сводка: {weeklyError}</p>}{weekly && <p>Неделя с {weekly.start}: исходящие {weekly.totals.calls}/200 · консультации {weekly.totals.consultations}/10 (цель15) · разговоры {weekly.totals.conversations}/20 · договоры {weekly.totals.contracts}/2. Дней с планом: {weekly.days.length}.</p>}
  </section>
}
