import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { DailyPlan, type Daily } from './DailyPlan'
import type { Plan } from './transport'

vi.mock('../lib/api', () => ({ api: vi.fn() }))
const daily: Daily = { revision: 1, contracts: 0, updated_at: 1, indicators: ['calls','new_leads','missed','consultations','pain','conversations','overdue','payments'].map(key => ({key,label:key,planned:0,actual:0,morning:0,remaining:0,source:'Снимок',details:[]})) }
const plan = { id: 1, employee_id: 1, employee_name: 'Synthetic', day: '2026-10-28', status: 'closed' } as Plan
beforeEach(() => {
  vi.mocked(api).mockReset()
  vi.mocked(api).mockImplementation(async resource => {
    if (resource.includes('/daily')) return daily as never
    if (resource.includes('/weekly')) return {start:plan.day,days:[],totals:{},targets:{}} as never
    throw new Error('Unexpected source refresh')
  })
})
it('closed plan without explicit snapshot never refreshes CRM sources', async () => {
  render(<DailyPlan plan={plan} />)
  await screen.findByText('1. calls')
  expect(vi.mocked(api).mock.calls.some(([url]) => url.includes('/sources/'))).toBe(false)
  expect(screen.queryByText('Повторить проверку источников')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Факт calls')).toBeDisabled()
})
it('saved report reads its immutable snapshot without fetching daily or CRM', async () => {
  render(<DailyPlan plan={plan} snapshot={daily} />)
  await waitFor(() => expect(screen.getByText('1. calls')).toBeInTheDocument())
  expect(vi.mocked(api).mock.calls.every(([url]) => url.includes('/weekly'))).toBe(true)
})
