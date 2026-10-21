/* Only tests.planner_browser_server --distributions, temporary DB/fake token. */
const { chromium } = require('playwright');
const { createHmac } = require('node:crypto');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:8765';
function data(id) {
  const v = { auth_date: String(Math.floor(Date.now()/1000)), user: JSON.stringify({id,first_name:'Test'}) };
  const key = createHmac('sha256','WebAppData').update('123456:synthetic_planner_test_token').digest();
  v.hash = createHmac('sha256',key).update(Object.entries(v).sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex');
  return new URLSearchParams(v).toString();
}
(async()=>{
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
  const errors=[];
  async function page(id) {
    const context=await browser.newContext({viewport:{width:390,height:844}});
    const p=await context.newPage();
    p.on('pageerror',e=>errors.push(e.message));
    await p.route('https://telegram.org/**',r=>r.abort());
    await p.addInitScript(d=>{window.Telegram={WebApp:{initData:d,ready(){},expand(){},onEvent(){},offEvent(){}}};},data(id));
    await p.goto(base);
    return p;
  }
  try {
    const yana=await page(7939114214);
    await yana.getByRole('heading',{name:'Обработка недозвонов',exact:true}).waitFor();
    await yana.getByText(/Источник: Утреннее распределение/).waitFor();
    assert.equal(await yana.getByText('Требует рассмотрения',{exact:true}).count(),0);
    await yana.getByRole('button',{name:'Подтвердить план',exact:true}).click();
    await yana.getByText('Подтверждён',{exact:true}).waitFor();
    await yana.getByRole('button',{name:'Начать',exact:true}).click();
    await yana.getByRole('button',{name:'Пауза',exact:true}).click();
    const manager=await page(8306778724);
    await manager.getByText('Требует рассмотрения',{exact:true}).waitFor();
    assert.equal(await manager.getByRole('heading',{name:'Обработка недозвонов',exact:true}).count(),0);
    const supervisor=await page(1073597301);
    await supervisor.getByText('Требует рассмотрения',{exact:true}).waitFor();
    assert.equal((await manager.request.get(base+'/api/distributions')).status(),401);
    assert.deepEqual(errors,[]);
    console.log('PASS: automatic queue import, source/dates/count, manager confirms own draft and uses timer, review for approved plan, supervisor visibility, auth.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
