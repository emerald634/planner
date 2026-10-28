export const dateTime = (value: string | null) =>
  value ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'

export const roleLabels = { admin: 'Администратор', supervisor: 'Руководитель', manager: 'Менеджер' }
export const syncLabels = { pending: 'Ожидает', synced: 'Синхронизирован', failed: 'Ошибка', abandoned: 'Не удалось', local: 'Только LeadFlow' }

