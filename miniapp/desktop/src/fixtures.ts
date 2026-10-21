import type { Employee, Plan, Task } from '../../src/types';

// demo-fixtures-ONLY: synthetic snapshots; never an auth or network adapter.
export const day = '2026-10-21';
export const snapshotTime = '21.10.2026, 11:05 МСК';
export const managers: Employee[] = [
  { id: 101, name: 'Алексей (демо)', role: 'manager', active: 1, telegram_id: null, bitrix_id: null },
  { id: 102, name: 'Мария (демо)', role: 'manager', active: 1, telegram_id: null, bitrix_id: null },
];
const titles = ['Обработка недозвонов', 'Подготовить предложение', 'Разобрать входящие задачи', 'Обсудить результаты встречи', 'Подвести итоги дня'];
function tasks(employee: Employee): Task[] {
  return titles.map((title, index) => ({ id: employee.id * 10 + index, plan_id: employee.id, employee_id: employee.id,
    title, description: 'Вымышленная задача для локального просмотра', kind: index === 0 ? 'quantitative' : 'general',
    planned_minutes: [70, 45, 40, 30, 20][index], target: index === 0 ? 12 : null, actual_value: index === 0 ? 5 : 0,
    actual_seconds: [1440, 2100, 1200, 0, 0][index], elapsed_seconds: [1440, 2100, 1200, 0, 0][index],
    timer_started: index === 0 ? 1792568460 : null, status: index === 0 ? 'in_progress' : index < 3 ? 'done' : 'todo',
    result: index < 3 ? 'Тестовый результат' : '', comment: '', locked: index === 0 ? 1 : 0, revision: 1,
    external_url: null, moved_to: null, distribution_target_locked: index === 0,
    ...(index === 0 ? { distribution_source: { name: 'Утреннее распределение', dates: ['2026-10-19', '2026-10-20'], count: 12 } } : {}),
  }));
}
export const plans: Plan[] = managers.map((employee, index) => {
  const items = tasks(employee);
  return { id: employee.id, employee_id: employee.id, employee_name: employee.name, day,
    status: index === 0 ? 'approved' : 'draft', tasks: items, server_time: 1792569900, initial_snapshot: null,
    summary: { total: items.length, done: items.filter(t => t.status === 'done').length, moved: 0,
      planned_minutes: items.reduce((n, t) => n + t.planned_minutes, 0), actual_seconds: items.reduce((n, t) => n + t.elapsed_seconds, 0) } };
});
