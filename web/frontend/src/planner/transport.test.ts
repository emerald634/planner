import { describe, expect, it } from 'vitest'
import { validatePlanner } from './transport'

describe('Planner runtime boundary', () => {
  it.each([null, {}, { user: { id: 1, name: 'Synthetic', active: '1', role: 'supervisor' } }, { user: { id: 1, name: 'Synthetic', active: 1, role: 'admin' } }])('rejects malformed identity %j', value => {
    expect(() => validatePlanner('/me', 'GET', value)).toThrow('неожиданного формата')
  })
  it('accepts a real identity contract and an empty employees list only after response', () => {
    expect(() => validatePlanner('/me', 'GET', { user: { id: 1, name: 'Synthetic', role: 'manager', active: 1 }, today: '2026-10-27', timezone: 'Europe/Moscow', crm: { connected: false, message: 'Недоступно' } })).not.toThrow()
    expect(() => validatePlanner('/employees', 'GET', [])).not.toThrow()
  })
  it.each(['/plans', '/employees', '/requests', '/plans/1/history'])('rejects an envelope instead of array at %s', path => {
    expect(() => validatePlanner(path, 'GET', { items: [] })).toThrow()
  })
  it('does not accept a partial plan as a usable plan', () => {
    expect(() => validatePlanner('/plans/1', 'GET', { id: 1, status: 'draft', tasks: [] })).toThrow()
  })
  it('task creation returns a task, while plan list returns summaries', () => {
    const task = { id: 1, revision: 1, title: 'Synthetic', kind: 'general', status: 'todo', planned_minutes: 30, actual_seconds: 0, actual_value: 0, locked: 0, description: '', result: '', comment: '', timer_started: null, target: null }
    expect(() => validatePlanner('/plans/1/tasks', 'POST', task)).not.toThrow()
    expect(() => validatePlanner('/plans', 'GET', [{ id: 1, employee_id: 2, employee_name: 'Synthetic', day: '2026-10-27', status: 'draft', summary: { total: 0, done: 0, planned_minutes: 0, actual_seconds: 0 } }])).not.toThrow()
  })
})
