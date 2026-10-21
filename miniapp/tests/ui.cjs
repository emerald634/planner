/* Isolated integration test. Start python -m tests.planner_browser_server first. */
const { chromium } = require('playwright');
const { createHmac } = require('node:crypto');
const { mkdir } = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const TOKEN = '123456:synthetic_planner_test_token';
const base = 'http://127.0.0.1:8765';

function initData(id) {
  const values = { auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id, first_name: 'Test' }) };
  const secret = createHmac('sha256', 'WebAppData').update(TOKEN).digest();
  values.hash = createHmac('sha256', secret).update(Object.entries(values).sort().map(([k,v]) => `${k}=${v}`).join('\n')).digest('hex');
  return new URLSearchParams(values).toString();
}

(async () => {
  const artifacts = path.resolve(__dirname, '../../test-artifacts');
  await mkdir(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const errors = [];
  async function pageFor(id, width = 390, theme = 'light') {
    const context = await browser.newContext({ viewport: { width, height: 844 }, colorScheme: theme });
    const page = await context.newPage();
    await page.route('https://telegram.org/**', route => route.abort());
    await page.addInitScript(({ data, theme }) => {
      window.Telegram = { WebApp: { initData: data, colorScheme: theme, ready() {}, expand() {}, onEvent() {}, offEvent() {} } };
    }, { data: initData(id), theme });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.getByRole('heading', { name: id === 1073597301 ? 'Планы' : 'Мой план дня', exact: true }).waitFor();
    return page;
  }
  async function clickSave(page) {
    await page.getByRole('dialog').getByRole('button', { name: 'Сохранить', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
  }
  async function fresh(page) {
    await page.getByRole('button', { name: 'Обновить', exact: true }).click();
    await page.waitForResponse(r => r.url().endsWith('/history'));
  }
  try {
    const manager = await pageFor(8306778724);
    await manager.getByRole('button', { name: 'Создать план', exact: true }).click();
    await manager.getByRole('button', { name: 'Новая задача' }).click();
    await manager.getByLabel('Название', { exact: true }).fill('Повторные звонки клиентам');
    await manager.getByLabel('Описание', { exact: true }).fill('Вернуться к клиентам, с которыми не удалось связаться.');
    await manager.getByLabel('Тип задачи').selectOption('quantitative');
    await manager.getByLabel('Плановое время, мин').fill('90');
    await manager.getByLabel('Плановая цель').fill('30');
    await clickSave(manager);
    await manager.getByRole('button', { name: 'Начать', exact: true }).click();
    await manager.getByRole('button', { name: 'Пауза', exact: true }).waitFor();
    await manager.reload();
    await manager.getByRole('button', { name: 'Пауза', exact: true }).click();
    await manager.getByRole('button', { name: 'Начать', exact: true }).waitFor();
    await manager.getByRole('button', { name: 'Внести результат', exact: true }).click();
    await manager.getByLabel('Факт', { exact: true }).fill('12');
    await manager.getByLabel('Затрачено, мин').fill('38');
    await clickSave(manager);
    await manager.getByRole('button', { name: 'Новая задача' }).click();
    await manager.getByLabel('Название', { exact: true }).fill('Подготовить предложение');
    await manager.getByLabel('Тип задачи').selectOption('client');
    await manager.getByLabel('Плановое время, мин').fill('40');
    await clickSave(manager);
    await manager.getByRole('status').waitFor({ state: 'hidden' });
    await manager.screenshot({ path: path.join(artifacts, 'planner-manager-mobile.png'), fullPage: true });
    assert(await manager.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile horizontal overflow');

    const supervisor = await pageFor(1073597301, 1200);
    await supervisor.getByLabel('Сотрудник', { exact: true }).selectOption('1');
    await supervisor.getByRole('button', { name: 'Утвердить план', exact: true }).click();
    await supervisor.getByText('План утверждён', { exact: true }).waitFor();
    await fresh(manager);
    const taskCard = manager.locator('.task').filter({ has: manager.getByRole('heading', { name: 'Повторные звонки клиентам' }) });
    await taskCard.getByText('Ещё', { exact: true }).click();
    await taskCard.getByRole('button', { name: 'Изменить цель / время' }).click();
    await manager.getByLabel('Что изменить').selectOption('target');
    await manager.getByLabel('Предложенное значение').fill('25');
    await manager.getByLabel('Причина', { exact: true }).fill('Потребовалось время на подготовку предложения');
    await manager.getByRole('button', { name: 'Отправить запрос', exact: true }).click();
    await manager.getByRole('dialog').waitFor({ state: 'hidden' });
    await fresh(supervisor);
    await supervisor.getByRole('navigation').getByRole('button', { name: /Запросы/ }).click();
    await supervisor.getByLabel('Комментарий к решению').fill('Согласовано');
    await supervisor.getByRole('button', { name: 'Утвердить', exact: true }).click();
    await supervisor.getByText('Решение сохранено', { exact: true }).waitFor();
    await supervisor.screenshot({ path: path.join(artifacts, 'planner-supervisor-desktop.png'), fullPage: true });
    await fresh(manager);
    await taskCard.getByRole('button', { name: 'Внести результат', exact: true }).click();
    assert.equal(await manager.getByLabel('Плановая цель').inputValue(), '25');
    assert(await manager.getByLabel('Плановая цель').isDisabled());
    await manager.getByRole('dialog').getByRole('button', { name: 'Отмена', exact: true }).click();
    const clientCard = manager.locator('.task').filter({ has: manager.getByRole('heading', { name: 'Подготовить предложение' }) });
    await clientCard.getByText('Ещё', { exact: true }).click();
    await clientCard.getByRole('button', { name: 'Перенести задачу' }).click();
    const next = new Date(); next.setDate(next.getDate() + 1);
    const tomorrow = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(next);
    await manager.getByLabel('Новая дата').fill(tomorrow);
    await manager.getByLabel('Причина переноса').fill('Продолжу завтра');
    await manager.getByRole('dialog').getByRole('button', { name: 'Перенести', exact: true }).click();
    await manager.getByRole('dialog').waitFor({ state: 'hidden' });
    await manager.getByRole('button', { name: 'Завершить рабочий день', exact: true }).click();
    await manager.getByRole('dialog').getByRole('button', { name: 'Завершить день', exact: true }).click();
    await manager.getByRole('heading', { name: 'Итоговый отчёт' }).waitFor();
    await manager.reload();
    await manager.getByRole('heading', { name: 'Итоговый отчёт' }).waitFor();
    assert.equal(await manager.getByRole('button', { name: 'Новая задача' }).count(), 0);

    const yana = await pageFor(7939114214);
    await yana.getByRole('button', { name: 'Создать план', exact: true }).click();
    await supervisor.getByRole('navigation').getByRole('button', { name: 'Планы', exact: true }).click();
    await supervisor.getByLabel('Сотрудник', { exact: true }).selectOption('2');
    await supervisor.getByRole('button', { name: 'Новая задача' }).click();
    await supervisor.getByLabel('Название', { exact: true }).fill('Задача Яне от руководителя');
    await supervisor.getByLabel('Плановое время, мин').fill('45');
    await clickSave(supervisor);
    await fresh(yana);
    await yana.getByRole('heading', { name: 'Задача Яне от руководителя' }).waitFor();
    await yana.getByRole('button', { name: 'Внести результат', exact: true }).click();
    assert(await yana.getByLabel('Название', { exact: true }).isDisabled());
    assert(await yana.getByLabel('Плановое время, мин').isDisabled());
    await yana.getByRole('dialog').getByRole('button', { name: 'Отмена', exact: true }).click();
    await yana.getByRole('button', { name: 'Подтвердить план', exact: true }).click();
    await yana.getByText('Подтверждён', { exact: true }).waitFor();
    assert.equal(await yana.getByRole('button', { name: 'Подтвердить план', exact: true }).count(), 0);
    await yana.getByRole('button', { name: 'Начать', exact: true }).click();
    await yana.getByRole('button', { name: 'Пауза', exact: true }).waitFor();
    await yana.getByRole('button', { name: 'Пауза', exact: true }).click();

    const dark = await pageFor(8306778724, 360, 'dark');
    await dark.getByRole('heading', { name: 'Итоговый отчёт' }).waitFor();
    await dark.screenshot({ path: path.join(artifacts, 'planner-report-dark-mobile.png'), fullPage: true });
    assert(await dark.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Dark mobile horizontal overflow');
    assert.equal((await manager.request.get(base + '/api/plans')).status(), 401);
    assert.equal((await manager.request.get(base + '/preview.html')).status(), 404);
    assert.deepEqual(errors, []);
    console.log('PASS: three employees, supervisor assignment to Yana, mobile manager, server timer restore, goal approval, move, immutable report, dark theme, auth, no production demo.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
