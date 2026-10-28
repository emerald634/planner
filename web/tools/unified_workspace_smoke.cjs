// One real login/layout/backend; private generated run only. Positive responses are never mocked.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const run = process.argv[2], visualOnly = process.argv.includes('--visual');
assert(/^lfweb_[a-f0-9]{32}$/.test(run));
const root = path.resolve(__dirname, '..'), scratch = path.resolve(root, '../.workbench/browser', run);
const meta = JSON.parse(fs.readFileSync(path.join(scratch, 'owner.json'), 'utf8'));
assert(meta.run_id === run && meta.kind === 'leadflow-planner-local-mvp');
const accounts = JSON.parse(fs.readFileSync(path.join(scratch, 'credentials.json'), 'utf8'));
const { chromium } = require(path.join(meta.planner_source, 'miniapp/node_modules/playwright'));
const origin = `http://127.0.0.1:${meta.port}`;
const output = path.resolve(root, '../unified-workspace-ui-20261027', visualOnly ? 'review' : run);
fs.mkdirSync(output, { recursive: true });
const checks = [], errors = [], external = [];
let failure, created;
async function login(page, role) {
  const account = accounts.find(a => a.email.startsWith(role + '@'));
  await page.goto(origin + '/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Пароль', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByRole('heading', { name: 'Главная', exact: true }).waitFor();
}
const nav = page => page.getByRole('navigation', { name: 'Основное меню', exact: true });
async function go(page, name) { await nav(page).getByRole('link', { name, exact: true }).click(); }
async function api(page, resource, method = 'GET', body) {
  return page.evaluate(async ({ resource, method, body }) => {
    const headers = { 'Content-Type': 'application/json' };
    if (method !== 'GET') headers['X-CSRF-Token'] = (await (await fetch('/api/v1/local/csrf', { credentials: 'include' })).json()).csrf;
    const response = await fetch('/api/v1' + resource, { method, headers, credentials: 'include', body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: response.status, value: await response.json() };
  }, { resource, method, body });
}
async function layout(page) {
  assert.equal(await page.locator('[data-testid="workspace-sidebar"]').count(), 1);
  assert.equal(await page.locator('.pw-topbar').count(), 1);
  assert.equal(await page.locator('.pw-profile').count(), 1);
  assert.equal(await nav(page).getByRole('link', { name: 'Главная', exact: true }).count(), 1);
  assert.equal(await page.getByRole('link', { name: /Обзор LeadFlow|Лиды LeadFlow/ }).count(), 0);
  assert.equal(await page.locator('main h1').count(), 1);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'document overflow');
  for (const el of await page.locator('main button:visible,main select:visible,main input:visible,main textarea:visible').all()) {
    const box = await el.boundingBox();
    assert(box && box.x >= 0 && box.x + box.width <= page.viewportSize().width + 1, 'clipped control');
  }
  assert.equal(await page.locator('.pw-workspace').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(12, 19, 35)');
}
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  let page;
  try {
    for (const role of ['manager', 'supervisor']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.route('**/*', route => {
        if (new URL(route.request().url()).origin !== origin) { external.push('blocked'); return route.abort(); }
        return route.continue();
      });
      page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
      await login(page, role);
      await page.locator('.pw-current-card,.pw-employee').first().waitFor();
      const token = (await context.cookies()).find(c => c.name === 'leadflow_local_session').value;
      await layout(page);
      await go(page, 'Лиды'); await page.locator('tbody tr').first().waitFor();
      await page.locator('tbody .lead-name').first().click();
      await page.getByRole('heading', { name: 'Информация о лиде', exact: true }).waitFor();
      await go(page, 'План дня');
      await page.getByRole('heading', { name: role === 'manager' ? 'Мой план' : 'Планы', exact: true }).waitFor();
      if (!visualOnly && role === 'manager') {
        const title = 'Единое приложение · искусственная задача ' + Date.now();
        await page.getByLabel('Название новой задачи').fill(title);
        await page.getByLabel('Тип новой задачи').selectOption('quantitative');
        await page.getByLabel('Цель новой задачи').fill('7');
        await page.getByRole('button', { name: 'Добавить задачу', exact: true }).click();
        await page.getByRole('heading', { name: title, exact: true }).waitFor();
        const summaries = await api(page, '/planner/plans');
        const plan = (await api(page, '/planner/plans/' + summaries.value.find(p => p.employee_id === 1).id)).value;
        const task = plan.tasks.find(t => t.title === title); created = { task: task.id, plan: plan.id, title };
        const card = page.locator(`[data-task-id="${task.id}"]`);
        await card.getByLabel('Фактическое количество').fill('2');
        await card.getByLabel('Результат', { exact: true }).fill('Сохранено в общем приложении');
        await card.getByRole('button', { name: 'Сохранить задачу', exact: true }).click();
        await page.reload(); await card.getByLabel('Результат', { exact: true }).waitFor();
        assert.equal(await card.getByLabel('Фактическое количество').inputValue(), '2');
        await card.getByRole('button', { name: 'Запустить таймер', exact: true }).click();
        await card.getByRole('button', { name: 'Остановить таймер', exact: true }).waitFor();
        await page.waitForTimeout(1200);
        await card.getByRole('button', { name: 'Остановить таймер', exact: true }).click();
        await card.getByRole('button', { name: 'Запустить таймер', exact: true }).waitFor();
        const saved = (await api(page, '/planner/plans/' + plan.id)).value;
        assert(saved.tasks.find(t => t.id === task.id).actual_seconds >= 1);
        if (saved.status === 'draft') { await page.getByRole('button', { name: 'Подтвердить план', exact: true }).click(); await page.getByText('Подтверждён', { exact: true }).first().waitFor(); }
        await card.getByRole('button', { name: 'Запросить изменение цели / времени' }).click();
        await card.getByLabel('Новое значение').fill('45');
        await card.getByLabel('Причина', { exact: true }).fill('Проверка общего рабочего пространства');
        await card.getByRole('button', { name: 'Отправить запрос', exact: true }).click();
        await go(page, 'Лиды'); await page.locator('tbody tr').first().waitFor();
        await go(page, 'План дня'); await card.getByLabel('Результат', { exact: true }).waitFor();
        assert.equal(await card.getByLabel('Результат', { exact: true }).inputValue(), 'Сохранено в общем приложении');
        assert.equal((await context.cookies()).find(c => c.name === 'leadflow_local_session').value, token);
        assert.equal((await api(page, '/planner/plans?employee_id=2')).status, 403);
        assert.equal((await api(page, '/users')).status, 403);
        checks.push('one manager login → home/leads/detail/plan/create/save/reload/timer/leads/plan; same session; rights');
      }
      if (!visualOnly && role === 'supervisor') {
        await page.getByLabel('Сотрудник', { exact: true }).selectOption('2');
        await page.waitForFunction(() => new URL(location.href).searchParams.get('employee') === '2');
        await page.getByLabel('Сотрудник', { exact: true }).selectOption('1');
        await go(page, 'Согласования');
        const request = page.locator('.pw-request').filter({ hasText: created.title });
        await request.getByRole('button', { name: 'Утвердить изменение' }).click();
        await request.getByText('Утверждено', { exact: false }).waitFor();
        await go(page, 'План дня');
        assert.equal(await page.locator(`[data-task-id="${created.task}"]`).getByLabel('Плановое время', { exact: true }).inputValue(), '45');
        await go(page, 'Сотрудники');
        await page.locator('.person-card').first().waitFor(); await page.locator('.pw-employee').first().waitFor();
        assert.equal(await page.getByRole('button', { name: 'Добавить', exact: true }).count(), 0);
        assert.equal((await api(page, '/users', 'POST', {})).status, 403);
        checks.push('supervisor plans/employee selection/approval; separate employee sources; no admin grant');
      }
      for (const [width, height] of [[1366,768],[1440,900],[1920,1080]]) {
        await page.setViewportSize({ width, height });
        for (const [name, key] of [['Главная','home'],['Лиды','leads'],['План дня','plan']]) {
          await go(page, name);
          if (key === 'home') { await page.locator('.pw-current-card,.pw-employee').first().waitFor(); await page.locator('.ui-recent-leads tbody tr').first().waitFor(); }
          if (key === 'leads') await page.locator('tbody tr').first().waitFor();
          if (key === 'plan') await page.locator('[data-task-id]').first().waitFor();
          await layout(page); await page.mouse.move(width - 2, 2);
          await page.screenshot({ path: path.join(output, `${role}-${key}-${width}x${height}.png`), fullPage: true });
          checks.push(`${role} ${key} ${width}x${height}: one sidebar/header/profile and dark theme`);
        }
      }
      await go(page, 'Аналитика'); await page.locator('.pw-no-data').nth(5).waitFor();
      assert.equal(await page.locator('.pw-no-data').count(), 6);
      await go(page, 'Настройки'); await page.getByRole('heading', { name: 'Мой профиль', exact: true }).waitFor();
      await layout(page);
      if (!visualOnly && role === 'manager') {
        await page.route('**/api/v1/stats/summary', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Искусственный отказ сводки' }) }));
        await go(page, 'Главная'); await page.getByRole('alert').filter({ hasText: 'Сводка лидов недоступна' }).waitFor();
        await page.locator('.pw-current-card').waitFor(); await page.locator('.ui-recent-leads tbody tr').first().waitFor();
        await page.unroute('**/api/v1/stats/summary'); await page.getByRole('button', { name: 'Повторить сводку лидов', exact: true }).click();
        await page.getByRole('alert').waitFor({ state: 'hidden' });
        await page.route('**/api/v1/planner/plans?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Искусственный отказ плана' }) }));
        await page.reload(); await page.getByRole('alert').filter({ hasText: 'Искусственный отказ плана' }).waitFor();
        await page.locator('.ui-recent-leads tbody tr').first().waitFor();
        await page.unroute('**/api/v1/planner/plans?*'); await page.getByRole('button', { name: 'Повторить загрузку плана', exact: true }).click();
        await page.locator('.pw-current-card').waitFor();
        for (const [view, destination] of Object.entries({ home: '/', plan: '/planner', tasks: '/planner/tasks', requests: '/planner/approvals', history: '/planner/history', report: '/planner/reports', metrics: '/statistics', employees: '/managers' })) {
          await page.goto(origin + '/planner?view=' + view);
          await page.waitForURL(url => url.pathname === destination && !url.searchParams.has('view'));
          await page.locator('main h1').waitFor();
        }
        await page.goto(origin + '/planner?view=tasks'); await page.getByLabel('Поиск задач', { exact: true }).waitFor();
        await page.getByLabel('Поиск задач', { exact: true }).fill('Несуществующий запрос поиска');
        await page.getByText('По выбранным условиям задач нет.', { exact: true }).waitFor();
        checks.push('independent failures/retry; legacy URLs; real task filters');
      }
      await context.close();
    }
    if (!visualOnly) {
      for (const role of ['admin','unmapped']) {
        const context = await browser.newContext(); page = await context.newPage();
        await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
        await login(page, role); await page.locator('.ui-recent-leads').waitFor();
        assert.equal((await api(page, '/planner/me')).status, 403);
        await go(page, 'Лиды'); await page.getByRole('heading', { name: 'Лиды', exact: true }).waitFor();
        if (role === 'admin') {
          assert.equal(await nav(page).getByRole('link', { name: 'План дня', exact: true }).count(), 0);
          await go(page, 'Сотрудники'); await page.getByRole('button', { name: 'Добавить', exact: true }).click();
          await page.getByRole('dialog', { name: 'Новый пользователь', exact: true }).waitFor();
          await page.getByRole('button', { name: 'Отмена', exact: true }).click();
          await page.locator('.person-card').filter({ hasText: 'Тестовый менеджер А' }).getByRole('button', { name: 'Редактировать', exact: true }).click();
          await page.getByRole('dialog', { name: 'Редактирование менеджера', exact: true }).waitFor();
          await page.getByRole('button', { name: 'Отмена', exact: true }).click();
        }
        checks.push(`${role}: Planner denied, LeadFlow remains usable`); await context.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
  } catch (error) { failure = error.message; if (page && !page.isClosed()) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); }
  finally { await browser.close(); }
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ success: !failure, run, checks, failure, errors, external_requests: external.length, mocked_successful_responses: 0, created }, null, 2));
  console.log(JSON.stringify({ success: !failure, checks: checks.length, failure }));
  if (failure) process.exitCode = 1;
})();
