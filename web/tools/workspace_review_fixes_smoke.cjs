// Owned synthetic run only. Observe actual request order; never mock a successful identity.
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const run=process.argv[2]; assert(/^lfweb_[a-f0-9]{32}$/.test(run));
const root=path.resolve(__dirname,'..'), scratch=path.resolve(root,'../.workbench/browser',run);
const meta=JSON.parse(fs.readFileSync(path.join(scratch,'owner.json'),'utf8'));
assert(meta.run_id===run && meta.kind==='leadflow-planner-local-mvp');
const accounts=JSON.parse(fs.readFileSync(path.join(scratch,'credentials.json'),'utf8'));
const {chromium}=require(path.join(meta.planner_source,'miniapp/node_modules/playwright'));
const origin=`http://127.0.0.1:${meta.port}`, output=path.resolve(root,'../workspace-review-fixes-20261027',run);
fs.mkdirSync(output,{recursive:true});
const checks=[], errors=[], external=[]; let failure, page;
const nav=()=>page.getByRole('navigation',{name:'Основное меню',exact:true});
const go=async name=>nav().getByRole('link',{name,exact:true}).click();
async function geometry(){
  assert.equal(await page.title(),'Рабочее пространство');
  assert.equal(await page.locator('.pw-sidebar').count(),1); assert.equal(await page.locator('.pw-topbar').count(),1); assert.equal(await page.locator('.pw-profile').count(),1);
  assert.equal(await page.getByRole('link',{name:'Главная — Рабочее пространство',exact:true}).count(),1);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  for(const element of await page.locator('main button:visible,main select:visible,main input:visible').all()){
    const box=await element.boundingBox(); assert(box && box.x>=0 && box.x+box.width<=page.viewportSize().width+1,'clipped control');
  }
}
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    for(const role of ['manager','supervisor','admin','unmapped']){
      const context=await browser.newContext({viewport:{width:1440,height:900}});
      await context.route('**/*',route=>{
        if(new URL(route.request().url()).origin!==origin){external.push('blocked'); return route.abort();} return route.continue();
      });
      page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
      let verified=false; const requests=[], premature=[], identityStatuses=[];
      page.on('request',request=>{
        const url=new URL(request.url()); if(!url.pathname.startsWith('/api/v1/planner/'))return;
        requests.push(url.pathname);
        if(url.pathname.endsWith('/me'))verified=false;
        else if(!verified)premature.push(url.pathname);
      });
      page.on('response',response=>{if(new URL(response.url()).pathname==='/api/v1/planner/me'){identityStatuses.push(response.status());if(response.status()===200)verified=true;}});
      await page.goto(origin+'/login');
      if(role==='manager')for(const [width,height]of[[1366,768],[1440,900],[1920,1080]]){
        await page.setViewportSize({width,height});assert.equal(await page.title(),'Рабочее пространство');
        assert.equal(await page.locator('.login-form-wrap').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(12, 19, 35)');
        await page.getByText('Рабочее пространство',{exact:true}).waitFor();
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await page.screenshot({path:path.join(output,`login-${width}x${height}.png`),fullPage:true});
      }
      let release;
      if(role==='manager'){
        const held=new Promise(resolve=>{release=resolve});
        await page.route('**/api/v1/planner/me',async route=>{await held;await route.continue();});
      }
      const account=accounts.find(item=>item.email.startsWith(role+'@'));
      await page.getByLabel('Email',{exact:true}).fill(account.email); await page.getByLabel('Пароль',{exact:true}).fill(account.password);
      await page.getByRole('button',{name:'Войти',exact:true}).click();
      await page.getByRole('heading',{name:'Главная',exact:true}).waitFor(); await page.locator('.ui-recent-leads').waitFor();
      if(role==='manager'){
        await page.getByText('Проверка доступа к плану…',{exact:true}).waitFor();
        assert.equal(requests.filter(p=>!p.endsWith('/me')).length,0);assert.equal(await nav().getByRole('link',{name:'План дня',exact:true}).count(),0);
        release();await page.locator('.pw-current-card').waitFor();await page.unroute('**/api/v1/planner/me');
        checks.push('pending identity: LeadFlow available; no data requests or Planner menu before real me200');
      }
      if(role==='supervisor')await page.locator('.pw-employee').first().waitFor();
      if(role==='unmapped'){await page.getByText('Проверка доступа к плану…',{exact:true}).waitFor({state:'hidden'});assert(identityStatuses.includes(403));}
      await page.getByRole('heading',{name:'Лиды LeadFlow',exact:true}).waitFor();
      assert.equal(await page.getByRole('heading',{name:'Лиды и распределение',exact:true}).count(),0);
      if(['admin','unmapped'].includes(role)){
        for(const name of ['Лиды','Аналитика',...(role==='admin'?['Сотрудники']:[]),'Главная']){
          await go(name);await page.locator('main h1').waitFor();
        }
        assert.equal(requests.filter(p=>!p.endsWith('/me')).length,0);
        assert.equal(requests.length,role==='admin'?0:1);
        assert.equal(await nav().getByRole('link',{name:'План дня',exact:true}).count(),0);
        assert.equal(await page.locator('.planner-web').count(),0);
        checks.push(`${role}: ordinary LeadFlow pages issue ${requests.length} identity probes, zero Planner data requests`);
      }
      const snapshotPage=role==='unmapped'?'/planner':'/';
      for(const [width,height]of[[1366,768],[1440,900],[1920,1080]]){
        await page.setViewportSize({width,height}); await page.goto(origin+snapshotPage);
        if(role==='unmapped')await page.getByRole('heading',{name:'План дня недоступен',exact:true}).waitFor();
        else {await page.getByRole('heading',{name:'Лиды LeadFlow',exact:true}).waitFor(); if(role==='manager')await page.locator('.pw-current-card').waitFor(); if(role==='supervisor')await page.locator('.pw-employee').first().waitFor();}
        await geometry();await page.mouse.move(width-2,2);await page.screenshot({path:path.join(output,`${role}-${width}x${height}.png`),fullPage:true});
        checks.push(`${role} ${width}x${height}: branding, single layout, no overflow`);
      }
      for(const route of ['/planner','/planner/tasks','/planner/approvals','/planner/history','/planner/reports']){
        await page.goto(origin+route);
        if(['admin','unmapped'].includes(role)){
          await page.getByRole('heading',{name:'План дня недоступен',exact:true}).waitFor();
          assert.equal(await page.locator('[data-task-id]').count(),0);
          if(role==='unmapped')await page.getByRole('alert').filter({hasText:'привязка'}).waitFor();
        }else{
          await page.getByRole('link',{name:'План дня',exact:true}).waitFor();await page.locator('.planner-web').waitFor();
        }
      }
      await page.goto(origin+'/planner?view=tasks');await page.waitForURL(url=>url.pathname==='/planner/tasks' && !url.searchParams.has('view'));
      if(['admin','unmapped'].includes(role))await page.getByRole('heading',{name:'План дня недоступен',exact:true}).waitFor();
      else await page.getByLabel('Поиск задач',{exact:true}).waitFor();
      assert.deepEqual(premature,[]);
      checks.push(`${role}: five direct routes + legacy link preserve the backend identity gate`);
      if(role==='manager'){
        for(const fault of ['503','network']){
          await page.route('**/api/v1/planner/me',route=>fault==='503'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Искусственный временный отказ'})}):route.abort('connectionreset'));
          const start=requests.length;await page.goto(origin+'/');
          await page.getByText(fault==='503'?'Планировщик временно недоступен':'Нет связи с планировщиком',{exact:true}).waitFor();
          await page.locator('.ui-recent-leads tbody tr').first().waitFor();
          assert.equal(await page.getByRole('heading',{name:'План дня недоступен',exact:true}).count(),0);
          assert.equal(requests.slice(start).filter(p=>!p.endsWith('/me')).length,0);
          await page.unroute('**/api/v1/planner/me');await page.getByRole('button',{name:'Повторить проверку доступа',exact:true}).click();
          await page.locator('.pw-current-card').waitFor();checks.push(`${fault}: separate temporary error; LeadFlow survives; retry uses real me and recovers`);
        }
      }
      await context.close();
    }
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }catch(error){failure=error.message;if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}
  finally{await browser.close();}
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({success:!failure,run,checks,failure,errors,external_requests:external.length,mocked_successful_responses:0},null,2));
  console.log(JSON.stringify({success:!failure,checks:checks.length,failure}));if(failure)process.exitCode=1;
})();
