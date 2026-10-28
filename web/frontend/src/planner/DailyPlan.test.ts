import { describe, expect, it } from 'vitest'
import { validateDaily } from './DailyPlan'

const value=()=>({revision:0,contracts:0,updated_at:null,indicators:['calls','new_leads','missed','consultations','pain','conversations','overdue','payments'].map(key=>({key,label:key,source:'manual',planned:0,actual:0,morning:0,remaining:0,details:[]}))})
describe('daily contract',()=>{
  it('accepts all eight rows and weekly contracts without ninth row',()=>expect(()=>validateDaily(value())).not.toThrow())
  it('rejects missing rows',()=>{const v=value();v.indicators.pop();expect(()=>validateDaily(v)).toThrow()})
  it('rejects duplicate indicator identities',()=>{const v=value();v.indicators[1].key='calls';expect(()=>validateDaily(v)).toThrow()})
  it('rejects invalid quantities',()=>{const v=value();v.indicators[0].actual=NaN;expect(()=>validateDaily(v)).toThrow()})
  it('rejects missing detail list',()=>{const v=value();Object.assign(v.indicators[0],{details:null});expect(()=>validateDaily(v)).toThrow()})
})
