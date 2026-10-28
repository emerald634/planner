import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it.each([
    ['pending', 'Ожидает'],
    ['synced', 'Синхронизирован'],
    ['failed', 'Ошибка'],
    ['abandoned', 'Не удалось'],
  ] as const)('renders the Russian label and CSS class for status "%s"', (status, label) => {
    render(<StatusBadge status={status} />)
    const badge = screen.getByText(label)
    expect(badge.closest('span')).toHaveClass(`badge-${status}`)
  })
})
