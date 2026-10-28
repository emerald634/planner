import { api } from '../lib/api'

export interface Employee { id: number; name: string; role: 'manager' | 'supervisor'; active: number }
export interface Task {
  id: number; title: string; description: string; revision: number; kind: string
  planned_minutes: number; target: number | null; actual_value: number; actual_seconds: number
  elapsed_seconds: number; timer_started: number | null; status: string; result: string; comment: string
  locked: number; distribution_target_locked?: boolean
  distribution_source?: { name: string; dates: string[]; count: number }
}
export interface Plan { id: number; day: string; employee_id: number; employee_name: string; status: 'draft' | 'approved' | 'closed'; tasks: Task[]; summary: { total: number; done: number; planned_minutes: number; actual_seconds: number } }
export interface Me { user: Employee; today: string; timezone: string; crm: { connected: boolean; message: string } }
export interface Goal { id: number; title: string; employee_name: string; field: string; old_value: number; proposed: number; reason: string; status: string; day: string }
export interface History { id: number; action: string; actor_name: string; created_at: number }

type ObjectValue = Record<string, unknown>
function object(value: unknown): value is ObjectValue { return !!value && typeof value === 'object' && !Array.isArray(value) }
function number(value: unknown) { return typeof value === 'number' && Number.isFinite(value) }
function id(value: unknown) { return number(value) && Number.isInteger(value) && (value as number) > 0 }
function employee(value: unknown) { return object(value) && id(value.id) && typeof value.name === 'string' && ['manager', 'supervisor'].includes(String(value.role)) && typeof value.active === 'number' && [0, 1].includes(value.active) }
function task(value: unknown) {
  return object(value) && id(value.id) && id(value.revision) && typeof value.title === 'string'
    && ['general', 'quantitative', 'client', 'bitrix'].includes(String(value.kind))
    && ['todo', 'in_progress', 'done', 'moved'].includes(String(value.status))
    && ['planned_minutes', 'actual_seconds', 'actual_value', 'locked'].every(key => number(value[key]))
    && ['description', 'result', 'comment'].every(key => typeof value[key] === 'string')
    && (value.timer_started === null || number(value.timer_started))
    && (value.target === null || number(value.target))
    && (value.distribution_target_locked === undefined || typeof value.distribution_target_locked === 'boolean')
    && (value.distribution_source === undefined || (object(value.distribution_source) && typeof value.distribution_source.name === 'string' && number(value.distribution_source.count) && Array.isArray(value.distribution_source.dates) && value.distribution_source.dates.every(day => typeof day === 'string')))
}
function planSummary(value: unknown) {
  return object(value) && id(value.id) && id(value.employee_id) && typeof value.day === 'string'
    && typeof value.employee_name === 'string' && ['draft', 'approved', 'closed'].includes(String(value.status))
    && object(value.summary) && ['total', 'done', 'planned_minutes', 'actual_seconds'].every(key => number((value.summary as ObjectValue)[key]))
}
function plan(value: unknown) {
  return planSummary(value) && object(value) && Array.isArray(value.tasks)
    && value.tasks.every(t => task(t) && object(t) && number(t.elapsed_seconds))
}
export function validatePlanner(path: string, method: string, value: unknown) {
  const route = path.split('?')[0]
  let valid: boolean
  if (route === '/me') valid = object(value) && employee(value.user) && typeof value.today === 'string' && typeof value.timezone === 'string' && object(value.crm) && typeof value.crm.message === 'string'
  else if (route === '/employees') valid = Array.isArray(value) && value.every(employee)
  else if (route === '/plans' && method === 'GET') valid = Array.isArray(value) && value.every(planSummary)
  else if (route.endsWith('/history')) valid = Array.isArray(value) && value.every(row => object(row) && number(row.id) && Number.isInteger(row.id) && row.id !== 0 && typeof row.action === 'string' && number(row.created_at))
  else if (route === '/requests') valid = Array.isArray(value) && value.every(row => object(row) && id(row.id) && typeof row.reason === 'string' && typeof row.title === 'string' && typeof row.status === 'string' && number(row.proposed))
  else if (route.includes('/requests')) valid = object(value) && id(value.id) && typeof value.status === 'string'
  else if (/^\/tasks\/\d+/.test(route) || /^\/plans\/\d+\/tasks$/.test(route)) valid = task(value)
  else valid = plan(value)
  if (!valid) throw new Error('Сервер вернул данные неожиданного формата. Обновите этот раздел.')
}
export async function plannerApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const value: unknown = await api('/planner' + path, options)
  try { validatePlanner(path, options.method || 'GET', value) }
  catch (error) {
    if (options.method && options.method !== 'GET') throw new Error(`${error instanceof Error ? error.message : 'Ошибка ответа'}. Изменение могло сохраниться: сначала обновите данные.`, { cause: error })
    throw error
  }
  return value as T
}
