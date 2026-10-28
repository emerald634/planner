import { describe, expect, it } from 'vitest'
import { dateTime, roleLabels, syncLabels } from './format'

describe('dateTime', () => {
  it('returns a dash for null', () => {
    expect(dateTime(null)).toBe('—')
  })

  it('formats an ISO date string', () => {
    const formatted = dateTime('2026-01-15T10:30:00Z')
    expect(formatted).toMatch(/2026/)
  })
})

describe('roleLabels', () => {
  it('has a Russian label for every role', () => {
    expect(roleLabels.admin).toBe('Администратор')
    expect(roleLabels.supervisor).toBe('Руководитель')
    expect(roleLabels.manager).toBe('Менеджер')
  })
})

describe('syncLabels', () => {
  it('has a label for every sync status including abandoned', () => {
    expect(syncLabels.pending).toBeTruthy()
    expect(syncLabels.synced).toBeTruthy()
    expect(syncLabels.failed).toBeTruthy()
    expect(syncLabels.abandoned).toBeTruthy()
  })
})
