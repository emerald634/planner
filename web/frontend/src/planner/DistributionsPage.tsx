import { useEffect, useState } from 'react'
import { api } from '../lib/api'

type Options = { managers: {id:number;name:string}[]; can_confirm:boolean; source:string; confirm_stage:string }
type Calculation = { id:string; workday:string; stages:string[]; dates:{day:string;count:number}[]; variants:{employee_id:number;name:string;dates:{day:string;count:number}[];count:number}[][] }
type History = { id:string;workday:string;status:string;reason:string;allocations:{name:string;count:number;dates:string[]}[] }
const errorText=(e:unknown)=>e instanceof Error?e.message:'Не удалось выполнить запрос'

export function DistributionsPage() {
  const [options,setOptions]=useState<Options>()
  const [selected,setSelected]=useState<number[]>([])
  const [period,setPeriod]=useState(3)
  const [stages,setStages]=useState(['IN_PROCESS'])
  const [calculation,setCalculation]=useState<Calculation>()
  const [variant,setVariant]=useState(0)
  const [history,setHistory]=useState<History[]>()
  const [error,setError]=useState('')
  const [historyError,setHistoryError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  const [retry,setRetry]=useState(0)
  useEffect(()=>{
    const controller=new AbortController()
    api<Options>('/planner/distribution/options',{signal:controller.signal}).then(x=>{if(!Array.isArray(x.managers)||typeof x.can_confirm!=='boolean')throw new Error('Ошибка формата настроек');if(!controller.signal.aborted){setOptions(x);setSelected(x.managers.map(m=>m.id))}}).catch(e=>{if(!controller.signal.aborted)setError(errorText(e))})
    return ()=>controller.abort()
  },[retry])
  useEffect(()=>{
    const controller=new AbortController()
    const load=()=>api<History[]>('/planner/distribution/history',{signal:controller.signal}).then(x=>{if(!Array.isArray(x)||!x.every(r=>typeof r.id==='string'&&Array.isArray(r.allocations)))throw new Error('Ошибка формата истории');if(!controller.signal.aborted){setHistory(x);setHistoryError('')}}).catch(e=>{if(!controller.signal.aborted)setHistoryError(errorText(e))})
    void load();const timer=setInterval(load,10000)
    return ()=>{clearInterval(timer);controller.abort()}
  },[retry])
  async function calculate(dates?:string[]){
    setBusy(true);setError('');setNotice('');setCalculation(undefined)
    try{const x=await api<Calculation>('/planner/distribution/calculate',{method:'POST',body:JSON.stringify({employee_ids:selected,period,stages,dates})});if(typeof x.id!=='string'||!Array.isArray(x.variants)||!Array.isArray(x.dates)||!x.variants.every(v=>Array.isArray(v)&&v.every(a=>typeof a.name==='string'&&Array.isArray(a.dates)&&Number.isInteger(a.count))))throw new Error('Ошибка формата расчёта');setCalculation(x);setVariant(0)}catch(e){setError(errorText(e))}finally{setBusy(false)}
  }
  async function replace(index:number,manual?:string){
    if(!calculation)return
    setBusy(true);setError('')
    try{let day=manual;if(!day){const found=await api<{day:string;count:number}|null>('/planner/distribution/previous',{method:'POST',body:JSON.stringify({before:calculation.dates[index].day,excluded:calculation.dates.map(d=>d.day),stages})});if(!found){setNotice('Предыдущих непустых дат нет. Можно продолжить без замены.');return}day=found.day}await calculate(calculation.dates.map((d,i)=>i===index?day!:d.day))}catch(e){setError(errorText(e))}finally{setBusy(false)}
  }
  async function confirm(){
    if(!calculation)return
    setBusy(true);setError('')
    try{const saved=await api<{workday:string;allocations:{name:string;count:number;dates:string[]}[]}>('/planner/distribution/'+calculation.id+'/confirm',{method:'POST',body:JSON.stringify({variant_index:variant})});if(!Array.isArray(saved.allocations))throw new Error('Ответ подтверждения неизвестен: проверьте историю перед повтором');setNotice(`Подтверждено ${saved.workday}: `+saved.allocations.map(a=>`${a.name}: ${a.count} · ${a.dates.join(', ')}`).join('; '));setRetry(x=>x+1)}catch(e){setError(errorText(e))}finally{setBusy(false)}
  }
  return <section className="planner-web"><h1>Распределение недозвонов</h1><p>Целые даты · общий дневной слот Telegram и web · CRM только чтение</p>{options&&<p className="pw-notice">{options.source}. Подтверждение первого этапа — только IN_PROCESS.</p>}
  {error&&<div role="alert" className="pw-error">{error}<button onClick={()=>{setError('');setRetry(x=>x+1)}}>Повторить загрузку</button></div>}{notice&&<p role="status" className="pw-notice">{notice}</p>}
  {!options&&!error&&<p role="status">Загрузка настроек распределения…</p>}
  {options&&<section className="pw-card"><fieldset disabled={busy}><legend>Параметры расчёта</legend><div className="pw-fields">{options.managers.map(m=><label key={m.id}><input type="checkbox" checked={selected.includes(m.id)} onChange={e=>{setCalculation(undefined);setSelected(e.target.checked?[...selected,m.id]:selected.filter(id=>id!==m.id))}}/>{m.name}</label>)}<label>Период<select aria-label="Период распределения" value={period} onChange={e=>{setPeriod(Number(e.target.value));setCalculation(undefined)}}>{[3,4,5,6,7,10,15].map(n=><option key={n} value={n}>{n} дней</option>)}</select></label>{[['IN_PROCESS','Недозвоны'],['PROCESSED','Неудобно говорить'],['NEW','Не обработан']].map(([id,label])=><label key={id}><input type="checkbox" checked={stages.includes(id)} onChange={e=>{setCalculation(undefined);setStages(e.target.checked?[...stages,id]:stages.filter(x=>x!==id))}}/>{label}</label>)}</div><button disabled={!selected.length||!stages.length} onClick={()=>calculate()}>Рассчитать распределение</button></fieldset></section>}
  {calculation&&<section className="pw-card"><h2>Даты и варианты · {calculation.workday}</h2><p>Пустые даты можно заменить или продолжить с текущими непустыми датами.</p>{calculation.dates.map((d,i)=><div className="pw-fields" key={d.day}><span>{d.day}: {d.count} лидов</span>{d.count===0&&<button disabled={busy} onClick={()=>replace(i)}>Подобрать предыдущую непустую</button>}<label>Другая дата<input aria-label={`Дата вместо ${d.day}`} type="date" defaultValue={d.day} disabled={busy} onBlur={e=>{if(e.target.value&&e.target.value!==d.day)void replace(i,e.target.value)}}/></label></div>)}<h3>Продолжить без замены / выбрать вариант</h3>{!calculation.variants.length&&<p>В выбранных датах лидов нет. Подтверждать нечего.</p>}{calculation.variants.map((v,i)=><label className="pw-history" style={{display:'block'}} key={i}><input type="radio" name="variant" checked={variant===i} disabled={busy} onChange={()=>setVariant(i)}/>Вариант {i+1}: {v.map(a=>`${a.name} — ${a.count}: ${a.dates.map(d=>d.day).join(', ')}`).join('; ')}</label>)}{options?.can_confirm&&calculation.stages.length===1&&calculation.stages[0]==='IN_PROCESS'&&calculation.variants.length>0&&<button disabled={busy} onClick={confirm}>✅ Подтвердить распределение</button>}{!options?.can_confirm&&<p>Расчёт доступен; отдельное право подтверждения не назначено.</p>}</section>}
  <section className="pw-card"><h2>История подтверждений и импорт</h2>{historyError&&<div role="alert">{historyError}<button onClick={()=>setRetry(x=>x+1)}>Повторить историю</button></div>}{!history&&!historyError&&<p role="status">Загрузка истории…</p>}{history?.length===0&&<p>Подтверждений нет.</p>}{history?.map(h=><article className="pw-history" key={h.id}><strong>{h.workday} · {{pending:'Ожидает импорта',imported:'Импортировано',review:'Требует рассмотрения'}[h.status]||'Ошибка импорта'}</strong>{h.allocations.map(a=><p key={a.name}>{a.name}: {a.count} · {a.dates.join(', ')}</p>)}{h.reason&&<p>План защищён или привязки требуют проверки; исходные данные сохранены без автоматической замены.</p>}</article>)}</section></section>
}
