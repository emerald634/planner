// Requires tests.planner_browser_server --hotfix: TEMPORARY SQLite/fake token only.
const {chromium,request}=require('playwright');
const {createHmac}=require('node:crypto');
const assert=require('node:assert/strict');
const base='http://127.0.0.1:8765';
function initData(id) {
  const values={auth_date:String(Math.floor(Date.now()/1000)),user:JSON.stringify({id,first_name:'Test'})};
  const secret=createHmac('sha256','WebAppData').update('123456:synthetic_planner_test_token').digest();
  values.hash=createHmac('sha256',secret).update(Object.entries(values).sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex');
  return new URLSearchParams(values).toString();
}
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const transport=await request.newContext({baseURL:base});
  const errors=[];
  try {
    for (const [id,title] of [[8306778724,'Хотфикс: Вячеслав'],[7939114214,'Хотфикс: Яна']]) {
      const headers={Authorization:'tma '+initData(id)};
      const me=await (await transport.get('/api/me',{headers})).json();
      const plan=await (await transport.post('/api/plans',{headers,data:{day:me.today}})).json();
      assert(plan.id,'start a clean temporary test server');
      assert.equal((await transport.post(`/api/plans/${plan.id}/tasks`,{headers,data:{title,kind:'quantitative',target:3,planned_minutes:15}})).status(),201);
    }
    async function pageFor(mode,target='/api/distributions',id=4444444444) {
      const context=await browser.newContext({viewport:{width:390,height:844}});
      const page=await context.newPage();
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('https://telegram.org/**',r=>r.abort());
      await page.addInitScript(({data,mode,target})=>{
        window.Telegram={WebApp:{initData:data,ready(){},expand(){},onEvent(){},offEvent(){}}};
        window.hotfixMode=mode;
        const nativeTimer=window.setTimeout.bind(window);
        window.setTimeout=(fn,ms,...args)=>nativeTimer(fn,ms===15000 && mode!=='delay'?600:ms,...args);
        const realFetch=window.fetch.bind(window);
        window.fetch=(url,options)=>{
          if(new URL(url,location.href).pathname!==target||window.hotfixMode==='none') return realFetch(url,options);
          if(window.hotfixMode==='pending') return new Promise(()=>{});
          if(window.hotfixMode==='body') return Promise.resolve({ok:true,status:200,json:()=>new Promise(()=>{})});
          if(window.hotfixMode==='delay') return new Promise(resolve=>{window.releaseHotfixStaff=()=>resolve(realFetch(url,options));});
          if(window.hotfixMode==='http') return Promise.resolve(new Response(JSON.stringify({detail:'Искусственный HTTP 503'}),{status:503}));
          if(window.hotfixMode==='format') return Promise.resolve(new Response(JSON.stringify({wrong:[]})));
          return realFetch(url,options);
        };
      },{data:initData(id),mode,target});
      await page.goto(base);
      await page.getByRole('heading',{name:id===8306778724?'Мой план дня':'Планы',exact:true}).waitFor();
      return page;
    }
    async function staff(page) {
      await page.getByRole('button',{name:'Менеджеры',exact:true}).click();
      await page.getByText('2 сотрудника в команде',{exact:true}).waitFor();
      assert.equal(await page.getByText('0 сотрудника в команде',{exact:true}).count(),0);
    }
    for (const mode of ['pending','body']) {
      const page=await pageFor(mode);
      await staff(page);
      await page.getByRole('button',{name:'Планы',exact:true}).click();
      await page.getByRole('button',{name:/Вячеслав/}).waitFor();
      const alert=page.getByRole('alert').filter({hasText:'Уведомления:'});
      await alert.waitFor();
      assert.equal(await page.getByText('Загружаем планы…',{exact:true}).count(),0);
      await page.getByLabel('Сотрудник',{exact:true}).selectOption('1');
      await page.getByRole('heading',{name:'Хотфикс: Вячеслав',exact:true}).waitFor();
      await page.evaluate(()=>{window.hotfixMode='none';});
      await alert.getByRole('button',{name:'Повторить загрузку'}).click();
      await alert.waitFor({state:'hidden'});
      await page.context().close();
    }
    for (const [target,label,mode] of [['/api/plans','Планы:','http'],['/api/plans','Планы:','format'],['/api/requests','Согласования:','http'],['/api/employees','Сотрудники:','format'],['/api/distributions','Уведомления:','format']]) {
      const page=await pageFor(mode,target);
      const alert=page.getByRole('alert').filter({hasText:label});
      await alert.waitFor();
      if(target!=='/api/employees') await staff(page);
      await page.evaluate(()=>{window.hotfixMode='none';});
      await alert.getByRole('button',{name:'Повторить загрузку'}).click();
      await alert.waitFor({state:'hidden'});
      await staff(page);
      await page.context().close();
    }
    const delayed=await pageFor('delay','/api/employees');
    await delayed.getByRole('button',{name:'Менеджеры',exact:true}).click();
    await delayed.getByText('Загрузка сотрудников',{exact:true}).waitFor();
    assert.equal(await delayed.getByText('0 сотрудника в команде',{exact:true}).count(),0);
    await delayed.evaluate(()=>window.releaseHotfixStaff());
    await delayed.getByText('2 сотрудника в команде',{exact:true}).waitFor();
    await delayed.context().close();
    const switching=await pageFor('none');
    await switching.getByLabel('Сотрудник',{exact:true}).waitFor();
    await switching.route('**/api/plans?employee_id=1',async route=>{await new Promise(r=>setTimeout(r,200));await route.continue();});
    await switching.getByLabel('Сотрудник',{exact:true}).selectOption('1');
    await switching.getByLabel('Сотрудник',{exact:true}).selectOption('2');
    await switching.getByRole('heading',{name:'Хотфикс: Яна',exact:true}).waitFor();
    await switching.waitForTimeout(300);
    assert.equal(await switching.getByRole('heading',{name:'Хотфикс: Вячеслав',exact:true}).count(),0);
    await switching.context().close();
    assert.equal((await transport.get('/api/me',{headers:{Authorization:'tma '+initData(1073597301)}})).status(),403);
    const manager=await pageFor('pending','/api/distributions',8306778724);
    await manager.getByRole('heading',{name:'Хотфикс: Вячеслав',exact:true}).waitFor();
    await manager.getByRole('button',{name:'Начать',exact:true}).click();
    await manager.getByRole('button',{name:'Пауза',exact:true}).click();
    assert.deepEqual(errors,[]);
    console.log('PASS: supervisor staff/plans/selection, independent pending distributions and JSON timeout, scoped errors/retry, malformed staff response, manager timer; no page errors.');
  } finally {await transport.dispose();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
