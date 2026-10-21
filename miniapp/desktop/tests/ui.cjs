// Isolated loopback Vite servers only. No backend, tokens, Telegram or SQLite.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:5174';
const production = 'http://127.0.0.1:5175';
const artifactDir = path.resolve(__dirname, '../../../test-artifacts/desktop');
const managerRoutes = ['Главная', 'Мой план', 'Задачи', 'Показатели', 'Обзвон действующих', 'Обзвон завершённых', 'История', 'Отчёты', 'Настройки'];
const supervisorRoutes = ['Обзор отдела', 'Сотрудники', 'Планы', 'Задачи и прогресс', 'Показатели', 'Согласования', 'История', 'Отчёты'];
async function assertNoOverflow(page) {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'horizontal overflow');
  for (const element of await page.locator('main button:visible,main select:visible').all()) {
    const box = await element.boundingBox();
    assert(box && box.x >= 0 && box.x + box.width <= (await page.viewportSize()).width, 'critical control clipped');
  }
}
(async () => {
  fs.mkdirSync(artifactDir, { recursive: true });
  const dist = path.resolve(__dirname, '../dist');
  const files = fs.readdirSync(path.join(dist, 'assets'));
  assert(!fs.existsSync(path.join(dist, 'demo.html')));
  for (const name of files) {
    const text = fs.readFileSync(path.join(dist, 'assets', name), 'utf8');
    for (const marker of ['demo-fixtures-ONLY', 'Алексей (демо)', 'Демонстрационная роль', 'Утреннее распределение']) assert(!text.includes(marker), 'demo leaked into production: ' + marker);
    assert(!name.endsWith('.map'));
  }
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  let navigations = 0;
  try {
    for (const [width, height] of [[1366,768],[1440,900],[1920,1080]]) {
      const context = await browser.newContext({ viewport: { width, height } });
      const errors = [], apiCalls = [], external = [];
      await context.route('**/*', route => {
        const u = new URL(route.request().url());
        if (u.origin !== base) { external.push(u.origin); return route.abort(); }
        if (u.pathname.startsWith('/api')) apiCalls.push(u.pathname);
        return route.continue();
      });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base + '/demo.html');
      await page.getByRole('heading', { level: 1, name: 'Главная', exact: true }).waitFor();
      assert.equal(await page.evaluate(() => typeof window.Telegram), 'undefined');
      assert.equal(await page.getByLabel('Сотрудник', { exact: true }).count(), 0);
      assert.equal(await page.getByRole('button', { name: 'Ⅱ Пауза', exact: true }).isDisabled(), true);
      const timer = await page.locator('.timer').innerText();
      await page.waitForTimeout(1100);
      assert.equal(await page.locator('.timer').innerText(), timer, 'independent local timer appeared');
      for (const role of ['manager', 'supervisor']) {
        await page.getByLabel('Демонстрационная роль').selectOption(role);
        const routes = role === 'manager' ? managerRoutes : supervisorRoutes;
        for (const label of routes) {
          await page.getByRole('navigation').getByRole('link', { name: label, exact: label !== 'Согласования' }).click();
          await page.getByRole('heading', { level: 1, name: label, exact: true }).waitFor();
          await assertNoOverflow(page); navigations++;
          if (label.startsWith('Обзвон ')) await page.getByText(/В разработке\. Клиенты/).waitFor();
          if (label === 'Показатели') {
            assert.equal(await page.getByText('Нет данных', { exact: true }).count(), 6);
            for (const period of ['Сегодня', 'Неделя', 'Месяц']) {
              await page.getByRole('button', { name: period, exact: true }).click();
              assert.equal(await page.getByText('Нет данных', { exact: true }).count(), 6);
            }
            if (role === 'manager') {
              assert.equal(await page.getByText('Норма начнёт действовать 01.11.2026', { exact: true }).count(), 6);
              await page.getByLabel('Дата периода').fill('2026-11-02');
              await page.getByRole('button', { name: 'Сегодня', exact: true }).click();
              await page.getByText('Норма: 35 наборов / день', { exact: true }).waitFor();
              await page.getByText('Цель: 80% · период требует уточнения', { exact: true }).waitFor();
              await page.getByText('Цель: 90% · период требует уточнения', { exact: true }).waitFor();
              await page.getByLabel('Дата периода').fill('2026-10-21');
            }
          }
        }
        await page.getByRole('navigation').getByRole('link', { name: routes[0], exact: true }).click();
        if (role === 'supervisor') {
          assert.equal(await page.locator('.employee-card').count(), 2);
          await page.getByLabel('Сотрудник', { exact: true }).selectOption('102');
          assert.equal(await page.locator('.employee-card').count(), 1);
          await page.locator('.employee-card').getByRole('heading', { name: 'Мария (демо)', exact: true }).waitFor();
          await page.getByLabel('Сотрудник', { exact: true }).selectOption('all');
        }
        await page.screenshot({ path: path.join(artifactDir, `${role}-${width}x${height}.png`), fullPage: true });
      }
      assert.deepEqual(errors, []); assert.deepEqual(apiCalls, []); assert.deepEqual(external, []);
      await context.close();
    }
    const context = await browser.newContext({ viewport: { width:1366,height:768 } });
    const page = await context.newPage();
    await page.goto(production + '/?role=supervisor&demo=true');
    await page.getByRole('heading', { name: /Рабочее пространство/ }).waitFor();
    assert.equal(await page.getByLabel('Демонстрационная роль').count(), 0);
    assert.equal(await page.locator('[data-demo]').count(), 0);
    const response = await page.request.get(production + '/demo.html');
    const content = await response.text();
    assert(!content.includes('/src/demo.tsx'));
    assert.equal(await page.locator('input[type=password]').count(), 0);
    assert.equal((await page.request.get(base + '/api/me')).status(), 403);
    const source = fs.readFileSync(path.resolve(__dirname, '../../src/api.ts'), 'utf8');
    assert(source.includes('Authorization: `tma ${initData}`'));
    assert(source.includes('if (!initData) throw'));
    await context.close();
    console.log(`PASS: ${navigations} navigation/viewport checks, two roles, manager scope, supervisor selection, metrics dates/periods, frozen server snapshot, no API/external/Telegram, 6 screenshots, production demo exclusion.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
