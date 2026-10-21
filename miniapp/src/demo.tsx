// Development-only visual fixture. This entry is not part of the production build.
// It never calls the real API and cannot authenticate to it.
import { createRoot } from 'react-dom/client';
import App from './App';
import type { Client, Employee, Plan, Task } from './types';
import './style.css';

if (!import.meta.env.DEV) throw new Error('Демонстрация доступна только локально.');
const params = new URLSearchParams(location.search);
document.documentElement.dataset.theme = params.get('theme') === 'dark' ? 'dark' : 'light';
const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const supervisor = params.get('role') === 'supervisor';
const staff: Employee[] = [
  { id: 1, name: 'Вячеслав (пример)', telegram_id: null, bitrix_id: null, role: 'manager', active: 1 },
  { id: 2, name: 'Яна (пример)', telegram_id: null, bitrix_id: null, role: 'manager', active: 1 },
];
const base: Task = { id: 1, plan_id: 1, employee_id: 1, title: '', description: '', kind: 'general', planned_minutes: 45, target: null, actual_value: 0, actual_seconds: 0, elapsed_seconds: 0, timer_started: null, status: 'todo', result: '', comment: '', locked: 0, revision: 1, external_url: null, moved_to: null };
const tasks: Task[] = [
  { ...base, title: 'Повторные звонки клиентам', description: 'Вернуться к клиентам, с которыми не удалось связаться.', kind: 'quantitative', planned_minutes: 90, target: 30, actual_value: 12, actual_seconds: 2280, elapsed_seconds: 2280, status: 'in_progress' },
  { ...base, id: 2, title: 'Подготовить предложение', kind: 'client', planned_minutes: 40, description: 'Собрать условия и согласовать следующий шаг.' },
  { ...base, id: 3, title: 'Разобрать входящие обращения', planned_minutes: 30, actual_seconds: 1500, elapsed_seconds: 1500, status: 'done', result: 'Все обращения разобраны', comment: 'Демонстрационный результат' },
];
const plans: Plan[] = staff.map((e, index) => ({ id: index + 1, employee_id: e.id, employee_name: e.name, day, status: 'approved', tasks: index === 0 ? tasks : [{ ...base, id: 4, plan_id: 2, employee_id: 2, title: 'Подготовка к встрече' }], summary: index === 0 ? { total: 3, done: 1, moved: 0, planned_minutes: 160, actual_seconds: 3780 } : { total: 1, done: 0, moved: 0, planned_minutes: 45, actual_seconds: 0 }, server_time: Math.floor(Date.now() / 1000), initial_snapshot: null }));
const demoClient: Client = async <T,>(path: string, method = 'GET'): Promise<T> => {
  if (method !== 'GET') throw new Error('Это демонстрация интерфейса. Для сохранения откройте приложение в Telegram.');
  let value: unknown;
  if (path === '/me') value = { user: supervisor ? { id: 3, name: 'Руководитель (пример)', role: 'supervisor', active: 1 } : staff[0], today: day, timezone: 'Europe/Moscow', crm: { connected: false, message: 'Bitrix24 не подключён. Все данные на экране — пример интерфейса.' } };
  else if (path === '/employees') value = staff;
  else if (path === '/requests') value = [{ id: 1, task_id: 1, employee_name: staff[0].name, title: tasks[0].title, day, field: 'target', old_value: 30, proposed: 25, reason: 'Больше времени на подготовку предложения — пример запроса.', status: 'pending', decision_comment: '', created_at: Math.floor(Date.now() / 1000), decided_at: null }];
  else if (/\/plans\/\d+\/history/.test(path)) value = [];
  else if (/\/plans\/\d+/.test(path)) value = plans.find(p => p.id === Number(path.split('/')[2]));
  else if (path.startsWith('/plans')) { const id = new URLSearchParams(path.split('?')[1]).get('employee_id'); value = id ? plans.filter(p => p.employee_id === Number(id)) : plans; }
  else throw new Error('Раздел недоступен в демонстрации.');
  return structuredClone(value) as T;
};
createRoot(document.getElementById('root')!).render(<App client={demoClient} demo/>);
