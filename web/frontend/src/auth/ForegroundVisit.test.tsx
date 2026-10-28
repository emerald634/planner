import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { ForegroundVisit } from './ForegroundVisit'
vi.mock('../lib/api',()=>({api:vi.fn().mockResolvedValue({visited:true})}))
afterEach(()=>{vi.clearAllMocks();vi.unstubAllEnvs();vi.useRealTimers()})
describe('foreground session visit',()=>{
  it('ordinary visible page reports visit through shared CSRF API',()=>{
    Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'})
    render(<ForegroundVisit />)
    expect(api).toHaveBeenCalledWith('/auth/visit',expect.objectContaining({method:'POST'}))
  })
  it('hidden tabs do not advance inactivity',()=>{
    vi.useFakeTimers();Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'})
    render(<ForegroundVisit />);vi.advanceTimersByTime(30*60*1000)
    expect(api).not.toHaveBeenCalled()
    Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'})
    document.dispatchEvent(new Event('visibilitychange'))
    expect(api).toHaveBeenCalledTimes(1)
  })
})
