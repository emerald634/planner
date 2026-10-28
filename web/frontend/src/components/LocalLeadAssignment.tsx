import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { User } from '../types'

export function LocalLeadAssignment({ leadId, refreshed }: { leadId:number; refreshed():void }) {
  const [managers,setManagers]=useState<User[]>()
  const [manager,setManager]=useState('')
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID())
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  useEffect(()=>{const c=new AbortController();api<User[]>('/users',{signal:c.signal}).then(rows=>{if(!Array.isArray(rows))throw new Error('Ошибка списка менеджеров');if(!c.signal.aborted)setManagers(rows.filter(m=>m.role==='manager'&&m.is_active))}).catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'Ошибка списка')});return()=>c.abort()},[])
  async function assign(){setBusy(true);setError('');setNotice('');try{await api(import.meta.env.VITE_LOCAL_PLANNER_MVP==='1'?`/local-leads/${leadId}/assign`:`/leads/${leadId}`,{method:import.meta.env.VITE_LOCAL_PLANNER_MVP==='1'?'POST':'PATCH',body:JSON.stringify(import.meta.env.VITE_LOCAL_PLANNER_MVP==='1'?{request_id:requestId,manager_id:manager?Number(manager):null}:{manager_id:Number(manager)})});setRequestId(crypto.randomUUID());setNotice('Назначение сохранено в LeadFlow.');refreshed()}catch(e){setError(e instanceof Error?e.message:'Ошибка назначения')}finally{setBusy(false)}}
  return <section className="panel"><h2>Назначение LeadFlow</h2><p>Существующий алгоритм нагрузки и смен; отдельный от недозвонов механизм.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}<label>Менеджер<select aria-label="Назначить лид менеджеру" value={manager} disabled={busy} onChange={e=>{setManager(e.target.value);setRequestId(crypto.randomUUID())}}><option value="">{import.meta.env.VITE_LOCAL_PLANNER_MVP==='1'?'Автоматически по нагрузке':'Выберите менеджера'}</option>{managers?.map(m=><option value={m.id} key={m.id}>{m.full_name}</option>)}</select></label><button disabled={busy||!managers||(import.meta.env.VITE_LOCAL_PLANNER_MVP!=='1'&&!manager)} onClick={assign}>Назначить лид</button></section>
}
