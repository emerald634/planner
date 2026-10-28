// Real Edge + real local backend. Never mocks successful API responses.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const run = process.argv[2];
assert(/^lfweb_[a-f0-9]{32}$/.test(run), 'Generated run ID required');
const scratch = path.resolve(root, '../.workbench/browser', run);
const meta = JSON.parse(fs.readFileSync(path.join(scratch, 'owner.json'), 'utf8'));
assert(meta.run_id === run && meta.kind === 'leadflow-planner-local-mvp');
const accounts = JSON.parse(fs.readFileSync(path.join(scratch, 'credentials.json'), 'utf8'));
const { chromium } = require(path.join(meta.planner_source, 'miniapp/node_modules/playwright'));
const origin = `http://127.0.0.1:${meta.port}`;
const artifacts = path.resolve(root, '../test-artifacts/browser-core', run);
fs.mkdirSync(artifacts, { recursive: true });
const checks = [];
function ok(name) { checks.push(name); console.log(name); }
async function login(page, role) {
  const account = accounts.find(a => a.email.startsWith(role + '@'));
  await page.goto(origin + '/login');
  await page.getByLabel('Email', { exact: true }).fill(account.email);
  await page.getByLabel('Пароль', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByTitle('Выйти').waitFor();
  if (role === 'admin' || role === 'unmapped') await page.goto(origin + '/planner');
  else await page.getByRole('link', { name: 'План дня', exact: true }).click();
}
async function api(page, resource, method = 'GET', body) {
  return page.evaluate(async ({ resource, method, body }) => {
    const headers = { 'Content-Type': 'application/json' };
    if (method !== 'GET') {
      const value = await (await fetch('/api/v1/local/csrf', { credentials: 'include' })).json();
      headers['X-CSRF-Token'] = value.csrf;
    }
    const response = await fetch('/api/v1' + resource, { method, headers,
      credentials: 'include', body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: response.status, value: await response.json() };
  }, { resource, method, body });
}
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const external = [];
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== origin) {
      external.push(new URL(route.request().url()).origin); return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    if (process.argv[3] === '--read-only') {
      const contract = JSON.parse(fs.readFileSync(path.join(artifacts, 'api-contract-results.json'), 'utf8'));
      await login(page, 'manager');
      await page.locator('[data-task-id]').first().waitFor();
      await page.screenshot({ path: path.join(artifacts, 'manager.png'), fullPage: true });
      await page.getByTitle('Выйти').click();
      await page.getByRole('button', { name: 'Войти', exact: true }).waitFor();
      await login(page, 'supervisor');
      await page.locator('[data-task-id]').first().waitFor();
      await page.screenshot({ path: path.join(artifacts, 'supervisor.png'), fullPage: true });
      const sessionBefore = (await context.cookies()).find(cookie => cookie.name === 'leadflow_local_session').value;
      await page.getByRole('link', { name: 'Лиды', exact: true }).click();
      await page.getByRole('link', { name: 'Тестовое обращение Б', exact: true }).waitFor();
      assert.equal(await page.locator('.unified-workspace').count(), 1, 'Same shared layout');
      assert.equal((await page.locator('.pw-sidebar').boundingBox()).width, 236, 'Same shared sidebar');
      assert.equal(await page.getByRole('button', { name: 'Добавить лид', exact: true }).count(), 0);
      await page.getByRole('link', { name: 'План дня', exact: true }).click();
      await page.locator('[data-task-id]').first().waitFor();
      assert.equal((await context.cookies()).find(cookie => cookie.name === 'leadflow_local_session').value, sessionBefore);
      await page.getByLabel('Дата плана', { exact: true }).fill(contract.saved_report.day);
      await page.getByText('День закрыт', { exact: true }).first().waitFor();
      await page.locator('.planner-web').getByRole('button', { name: 'Отчёт', exact: true }).click();
      await page.getByText('Контрактная синтетическая задача', { exact: true }).waitFor();
      await page.getByText('Сохранено', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(artifacts, 'report.png'), fullPage: true });
      await page.locator('.planner-web').getByRole('button', { name: 'История', exact: true }).click();
      await page.locator('.pw-history').filter({ hasText: 'День закрыт' }).waitFor();
      for (const width of [1024, 390]) {
        await page.setViewportSize({ width, height: 844 });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
      }
      assert.deepEqual(errors, []); assert.equal(external.length, 0);
      fs.writeFileSync(path.join(artifacts, 'readonly-results.json'), JSON.stringify({ success: true, report_from_real_backend: true, closed_history: true, leadflow_read_only: true, same_session_for_modules: true, widths_checked: [1024, 390] }, null, 2));
      console.log(JSON.stringify({ success: true, real_report: true, responsive: true }));
      return;
    }
    const anonymous = await context.request.get(origin + '/api/v1/planner/me');
    assert.equal(anonymous.status(), 401); ok('unauthenticated denied');
    await login(page, 'manager');
    await page.getByRole('heading', { name: 'Мой план', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Добавить задачу', exact: true }).waitFor();
    const title = ('Проверка рабочего MVP: длинное название задачи для проверки переноса строк и доступности действий. '.repeat(2)).slice(0, 140) + ' ' + Date.now();
    await page.getByLabel('Название новой задачи').fill(title);
    await page.getByLabel('Тип новой задачи').selectOption('quantitative');
    await page.getByLabel('Цель новой задачи').fill('10');
    await page.getByRole('button', { name: 'Добавить задачу', exact: true }).click();
    await page.getByRole('heading', { name: title, exact: true }).waitFor();
    const plans = await api(page, '/planner/plans');
    assert.equal(plans.status, 200);
    const summary = plans.value.find(p => p.employee_id === 1);
    const plan = (await api(page, '/planner/plans/' + summary.id)).value;
    assert(plan);
    const task = plan.tasks.find(t => t.title === title);
    let card = page.locator(`[data-task-id="${task.id}"]`);
    await card.getByLabel('Фактическое количество').fill('3');
    await card.getByLabel('Результат', { exact: true }).fill('Сохранённый тестовый результат');
    await card.getByLabel('Комментарий', { exact: true }).fill('Синтетическая проверка сохранения длинного комментария. '.repeat(50));
    await card.getByRole('button', { name: 'Сохранить задачу' }).click();
    await page.reload();
    card = page.locator(`[data-task-id="${task.id}"]`);
    await card.getByLabel('Результат', { exact: true }).waitFor();
    assert.equal(await card.getByLabel('Результат', { exact: true }).inputValue(), 'Сохранённый тестовый результат');
    const savedComment = await card.getByLabel('Комментарий', { exact: true }).inputValue();
    await card.getByLabel('Комментарий', { exact: true }).fill('Несохранённая правка');
    await card.getByRole('button', { name: 'Отмена', exact: true }).click();
    assert.equal(await card.getByLabel('Комментарий', { exact: true }).inputValue(), savedComment);
    await page.getByLabel('Название новой задачи').fill('Не создавать');
    await page.getByRole('button', { name: 'Отмена создания', exact: true }).click();
    assert.equal(await page.getByLabel('Название новой задачи').inputValue(), '');
    ok('cancel restores unsaved form values without a mutation');
    for (const [width, height] of [[1366,768],[1440,900],[1920,1080]]) {
      await page.setViewportSize({ width, height });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(artifacts, `long-form-manager-${width}x${height}.png`), fullPage: true });
    }
    ok('manager create/edit survives full page reload');
    assert.equal((await api(page, '/planner/employees')).status, 403);
    assert.equal((await api(page, '/planner/plans?employee_id=2')).status, 403);
    assert.equal((await api(page, '/planner/plans/2')).status, 403);
    ok('manager cannot read other employee or supervisor API');
    if (plan.status === 'draft') await page.getByRole('button', { name: 'Подтвердить план', exact: true }).click();
    else assert.equal((await api(page, `/planner/plans/${plan.id}/confirm`, 'POST')).status, 200);
    await page.getByText('Подтверждён', { exact: true }).first().waitFor();
    card = page.locator(`[data-task-id="${task.id}"]`);
    await card.getByRole('button', { name: 'Запустить таймер' }).click();
    await card.getByRole('button', { name: 'Остановить таймер' }).waitFor();
    await page.waitForTimeout(1300);
    await card.getByRole('button', { name: 'Остановить таймер' }).click();
    await card.getByRole('button', { name: 'Запустить таймер' }).waitFor();
    const timed = await api(page, '/planner/plans/' + plan.id);
    assert(timed.value.tasks.find(t => t.id === task.id).actual_seconds >= 1);
    ok('confirmed manager plan supports real server timer');
    card = page.locator(`[data-task-id="${task.id}"]`);
    await card.getByRole('button', { name: 'Запросить изменение цели / времени' }).click();
    await card.getByLabel('Новое значение').fill('45');
    await card.getByLabel('Причина', { exact: true }).fill('Нужно больше времени для искусственной задачи');
    await card.getByRole('button', { name: 'Отправить запрос' }).click();
    await page.locator('.planner-web').getByRole('button', { name: 'Согласования', exact: true }).click();
    await page.locator('.pw-request').filter({ hasText: title }).getByText('Ожидает решения', { exact: false }).waitFor();
    await page.screenshot({ path: path.join(artifacts, 'manager-requests.png'), fullPage: true });
    await page.getByRole('button', { name: 'План и задачи', exact: true }).click();
    await card.getByLabel('Результат', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(artifacts, 'manager.png'), fullPage: true });
    await page.getByTitle('Выйти').click();
    await page.getByRole('button', { name: 'Войти', exact: true }).waitFor();
    await login(page, 'supervisor');
    await page.getByRole('heading', { name: 'Планы', exact: true }).waitFor();
    await page.getByLabel('Сотрудник', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Сотрудник', { exact: true }).locator('option').count(), 2);
    const employeeTwo = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/planner/plans/2' && response.status() === 200);
    await page.getByLabel('Сотрудник', { exact: true }).selectOption('2');
    assert.equal((await (await employeeTwo).json()).employee_id, 2);
    await page.waitForFunction(() => new URL(location.href).searchParams.get('employee') === '2');
    await page.getByLabel('Сотрудник', { exact: true }).selectOption('1');
    card = page.locator(`[data-task-id="${task.id}"]`);
    await card.getByLabel('Название задачи', { exact: true }).fill(title + ' — проверено');
    await card.getByRole('button', { name: 'Сохранить задачу' }).click();
    await page.getByRole('heading', { name: title + ' — проверено', exact: true }).waitFor();
    await page.locator('.planner-web').getByRole('button', { name: 'Согласования', exact: true }).click();
    await page.locator('.pw-request').filter({ hasText: title }).getByRole('button', { name: 'Утвердить изменение' }).click();
    await page.locator('.pw-request').filter({ hasText: title }).getByText('Утверждено', { exact: false }).waitFor();
    await page.getByRole('button', { name: 'План и задачи', exact: true }).click();
    await page.reload();
    await page.getByRole('heading', { name: 'Планы', exact: true }).waitFor();
    await page.getByRole('heading', { name: title + ' — проверено', exact: true }).waitFor();
    assert.equal(await page.locator(`[data-task-id="${task.id}"]`).getByLabel('Плановое время', { exact: true }).inputValue(), '45');
    for (const [width, height] of [[1366,768],[1440,900],[1920,1080]]) {
      await page.setViewportSize({ width, height });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(artifacts, `long-form-supervisor-${width}x${height}.png`), fullPage: true });
    }
    await page.screenshot({ path: path.join(artifacts, 'supervisor.png'), fullPage: true });
    ok('supervisor sees two managers, selects employee, edits and approves real request');
    await page.locator('.planner-web').getByRole('button', { name: 'История', exact: true }).click();
    await page.getByText('План подтверждён', { exact: false }).waitFor();
    ok('history comes from original Store audit');
    await page.getByRole('button', { name: 'План и задачи', exact: true }).click();
    // Negative fault injection ONLY. All successful actions above used real API responses.
    await page.route('**/api/v1/planner/requests', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Искусственный отказ запросов' }) }));
    await page.reload();
    await page.getByRole('heading', { name: title + ' — проверено', exact: true }).waitFor();
    await page.locator('.planner-web').getByRole('button', { name: 'Согласования', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Искусственный отказ запросов' }).waitFor();
    await page.unroute('**/api/v1/planner/requests');
    await page.getByRole('button', { name: 'Повторить загрузку запросов' }).click();
    await page.getByText('Утверждено', { exact: false }).first().waitFor();
    await page.route('**/api/v1/planner/plans/*/history', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{broken' }), { times: 1 });
    await page.locator('.planner-web').getByRole('button', { name: 'История', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'некорректный JSON' }).waitFor();
    await page.getByRole('button', { name: 'Обновить план', exact: true }).click();
    await page.getByText('План подтверждён', { exact: false }).waitFor();
    ok('section failure and invalid JSON recover without blocking plans');
    const missingCsrf = await context.request.post(origin + '/api/v1/planner/plans', { headers: { Origin: origin }, data: { day: plan.day, employee_id: 2 } });
    assert.equal(missingCsrf.status(), 403);
    const crossSite = await context.request.post(origin + '/api/v1/planner/plans', { headers: { Origin: 'https://foreign.invalid' }, data: {} });
    assert.equal(crossSite.status(), 403); ok('missing CSRF and cross-site mutations denied');
    const userCreation = await api(page, '/users', 'POST', {});
    assert.equal(userCreation.status, 403); ok('supervisor has no admin create-user rights');
    await page.getByTitle('Выйти').click();
    await page.getByRole('button', { name: 'Войти', exact: true }).waitFor();
    await login(page, 'unmapped');
    await page.getByRole('alert').filter({ hasText: 'привязка' }).waitFor();
    ok('unmapped user denied Planner');
    await page.getByTitle('Выйти').click();
    await page.getByRole('button', { name: 'Войти', exact: true }).waitFor();
    await login(page, 'admin');
    await page.getByRole('heading', { name: 'План дня недоступен', exact: true }).waitFor();
    ok('LeadFlow admin does not become Planner supervisor');
    assert.equal(external.length, 0, 'No external browser requests permitted');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(artifacts, 'smoke-results.json'), JSON.stringify({ success: true, checks, plan_id: plan.id, task_id: task.id, external_requests: 0, mocked_successful_responses: 0 }, null, 2));
    console.log(JSON.stringify({ success: true, checks: checks.length, screenshots: artifacts }));
  } catch (error) {
    await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true });
    fs.writeFileSync(path.join(artifacts, process.argv[3] === '--read-only' ? 'readonly-results.json' : 'smoke-results.json'), JSON.stringify({ success: false, checks, error: error.message }, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
