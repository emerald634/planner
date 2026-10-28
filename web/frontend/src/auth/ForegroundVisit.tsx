import { useEffect } from 'react'
import { api } from '../lib/api'

// Actual visible-page use, not background requests, extends the inactivity clock.
export function ForegroundVisit() {
  useEffect(()=>{
    if(import.meta.env.VITE_LOCAL_PLANNER_MVP==='1')return
    const controller=new AbortController()
    const visit=()=>{if(document.visibilityState==='visible')void api('/auth/visit',{method:'POST',signal:controller.signal}).catch(()=>{})}
    visit();document.addEventListener('visibilitychange',visit)
    const timer=setInterval(visit,15*60*1000)
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',visit);controller.abort()}
  },[])
  return null
}
