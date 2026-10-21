export type Period = 'day' | 'week' | 'month';
export interface Metric {
  key: string; name: string; description: string; norm: number; unit: string;
  period: 'day' | 'week' | 'unspecified'; effectiveFrom: string; source: string;
  fact: number | null; progress: number | null; updatedAt: string | null; availability: 'not_connected';
}
// Requirements supplied by the owner. No CRM facts or inferred monthly norms.
export const metrics: Metric[] = [
  { key: 'attempts', name: 'Честные наборы', description: 'Отдельный показатель попыток звонка', norm: 35, unit: 'наборов', period: 'day' },
  { key: 'leads', name: 'Дозвоны по лидам', description: 'Разговоры продолжительностью от 1 минуты', norm: 8, unit: 'дозвонов', period: 'day' },
  { key: 'consultations', name: 'Консультации', description: 'Консультации продолжительностью от 10 минут', norm: 12, unit: 'консультаций', period: 'week' },
  { key: 'clients', name: 'Прозвон клиентов', description: 'Разговоры с клиентами от 2 минут', norm: 15, unit: 'разговоров', period: 'week' },
  { key: 'speed', name: 'Скорость первого звонка', description: 'Доля первых звонков в течение 15 минут', norm: 80, unit: '%', period: 'unspecified' },
  { key: 'callbacks', name: 'Перезвоны вовремя', description: 'В пределах ±15 минут от назначенного времени', norm: 90, unit: '%', period: 'unspecified' },
].map(value => ({ ...value, period: value.period as Metric['period'], effectiveFrom: '2026-11-01', source: 'Bitrix24 / телефония — не подключены', fact: null, progress: null, updatedAt: null, availability: 'not_connected' }));

export function normLabel(metric: Metric, day: string, period: Period): string {
  if (day < metric.effectiveFrom) return 'Норма начнёт действовать 01.11.2026';
  if (metric.period === 'unspecified') return `Цель: ${metric.norm}${metric.unit} · период требует уточнения`;
  if (period !== metric.period) return `Норма: ${metric.norm} ${metric.unit} / ${metric.period === 'day' ? 'день' : 'неделю'} · пересчёт не настроен`;
  return `Норма: ${metric.norm} ${metric.unit} / ${period === 'day' ? 'день' : 'неделю'}`;
}
