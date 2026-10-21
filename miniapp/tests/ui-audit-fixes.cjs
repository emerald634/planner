// Fully intercepted Edge regression tests. No server, real tokens, CRM or databases.
// Run after pnpm run build: node tests/ui-audit-fixes.cjs
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://audit-fixes.test';
const today = '2026-10-15', tomorrow = '2026-10-16';
const employees = [
  {id:1,name:'Тестовый менеджер А',role:'manager',active:1,telegram_id:101,bitrix_id:11},
  {id:2,name:'Тестовый менеджер Б',role:'manager',active:1,telegram_id:102,bitrix_id:12},
];
const copy = value => structuredClone(value);
const summary = tasks => ({total:tasks.length,done:0,moved:0,planned_minutes:10,actual_seconds:0});
function makePlan(id, employee, day) {
  const tasks = [{id:id*10,plan_id:id,employee_id:employee.id,title:`Задача ${id}`,description:'',kind:'quantitative',planned_minutes:10,target:3,actual_value:0,actual_seconds:0,revision:1,locked:0,status:'todo',result:'',comment:'',timer_started:null,external_url:null}];
  return {id,employee_id:employee.id,employee_name:employee.name,day,status:'draft',tasks,summary:summary(tasks),server_time:1792047600,initial_snapshot:null};
}
async function fixture(browser, options={}) {
  const context = await browser.newContext({viewport:{width:1200,height:900}});
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const errors = [], calls = [];
  page.on('pageerror',e=>errors.push(e.message));
  const state = {
    plans:[makePlan(11,employees[0],today),makePlan(12,employees[0],tomorrow),makePlan(21,employees[1],today),makePlan(22,employees[1],tomorrow)],
    requests:[{id:1,task_id:110,employee_name:employees[0].name,title:'Согласование А',day:today,field:'target',status:'pending',old_value:3,proposed:4,reason:'Тест',decision_comment:'',decided_at:null}],
    historyError:false, historyHold:null, mutationHold:null, override:null,
  };
  if(options.prepare) options.prepare(state);
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'synthetic-audit-only',ready(){},expand(){},onEvent(){},offEvent(){}}};});
  const send = (route,value,status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
  await page.route('**/*',async route=>{
    const request=route.request(), u=new URL(request.url()), method=request.method(), routePath=u.pathname.replace(/^\/api/,'');
    if(u.origin!==base) return route.abort();
    if(!u.pathname.startsWith('/api/')) {
      const relative=u.pathname==='/'?'index.html':u.pathname.slice(1);
      const file=path.resolve(__dirname,'../dist',relative);
      assert(file.startsWith(path.resolve(__dirname,'../dist')+path.sep));
      return route.fulfill({path:file,contentType:relative.endsWith('.js')?'application/javascript':relative.endsWith('.css')?'text/css':'text/html'});
    }
    calls.push({path:routePath,method});
    if(state.override) {
      const value=state.override(routePath,method);
      if(value!==undefined) return send(route,value);
    }
    if(method==='GET') {
      if(routePath==='/me') return send(route,{user:options.supervisor?{id:options.supervisor,name:'Тестовый руководитель',role:'supervisor',active:1,telegram_id:options.supervisor}:employees[0],today,timezone:'Europe/Moscow',workday:{start:'10:00',end:'19:00',timezone:'Europe/Moscow',reminders_enabled:false},crm:{connected:false,message:'Тестовые данные'}});
      if(routePath==='/employees') return send(route,employees);
      if(routePath==='/requests') return send(route,state.requests);
      if(routePath==='/distributions') return send(route,[]);
      if(routePath==='/plans') return send(route,state.plans.filter(p=>!u.searchParams.has('employee_id')||p.employee_id===Number(u.searchParams.get('employee_id'))));
      const match=routePath.match(/^\/plans\/(\d+)(\/history|\/report)?$/);
      if(match) {
        const id=Number(match[1]);
        if(match[2]==='/history') {
          if(state.historyHold) await state.historyHold(id);
          if(state.historyError && id===11) return send(route,{detail:'Временная ошибка истории 11'},503);
          return send(route,[{id,created_at:1792047600,actor_name:`История плана ${id}`,action:'plan_created',entity:'plan',entity_id:id,before_json:null,after_json:{day:state.plans.find(p=>p.id===id)?.day}}]);
        }
        return send(route,state.plans.find(p=>p.id===id));
      }
    } else {
      const data=request.postDataJSON();
      if(state.mutationHold) await state.mutationHold(routePath,method);
      let match=routePath.match(/^\/tasks\/(\d+)(\/timer|\/requests)?$/);
      if(match) {
        const task=state.plans.flatMap(p=>p.tasks).find(t=>t.id===Number(match[1]));
        if(match[2]==='/timer') {task.timer_started=data.action==='start'?1792047600:null;task.status=data.action==='start'?'in_progress':'todo';}
        else if(match[2]==='/requests') {const value={...state.requests[0],id:2,status:'pending',proposed:data.proposed};state.requests.push(value);return send(route,value);}
        else Object.assign(task,data,{revision:task.revision+1});
        return send(route,task);
      }
      match=routePath.match(/^\/plans\/(\d+)\/(tasks|confirm|approve)$/);
      if(match) {
        const plan=state.plans.find(p=>p.id===Number(match[1]));
        if(match[2]==='tasks') {const task={...plan.tasks[0],...data,id:999};plan.tasks.push(task);plan.summary=summary(plan.tasks);return send(route,task,201);}
        plan.status='approved';return send(route,plan);
      }
      if(routePath==='/requests/1/decision') {state.requests[0].status=data.decision;return send(route,state.requests[0]);}
    }
    return send(route,{detail:'Unknown synthetic route'},404);
  });
  await page.goto(base);
  return {page,state,calls,errors,close:()=>context.close()};
}
const task = (page,id) => page.getByRole('heading',{name:`Задача ${id}`,exact:true});
async function currentPlan(page,id) {await task(page,id).waitFor();await page.getByRole('button',{name:'Обновить',exact:true}).waitFor({state:'visible'});}
async function choose(page,employee,day) {
  if(employee) await page.getByLabel('Сотрудник',{exact:true}).selectOption(String(employee));
  if(day) await page.getByLabel('Дата плана',{exact:true}).fill(day);
}
function gate() {let release,entered;const ready=new Promise(r=>entered=r),wait=new Promise(r=>release=r);return {ready,release,hold:async()=>{entered();await wait;}};}
const save = page => page.getByRole('dialog').getByRole('button',{name:'Сохранить',exact:true}).click();

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
  const failures=[];
  let passed=0;
  async function run(name,fn) {
    try {await fn();passed++;console.log('PASS: '+name);}
    catch(e) {failures.push(name);console.error('FAIL: '+name+' — '+e.message);}
  }
  try {
    const operations = {
      start:async p=>p.getByRole('button',{name:'Начать',exact:true}).click(),
      stop:async p=>p.getByRole('button',{name:'Стоп',exact:true}).click(),
      edit:async p=>{await p.getByRole('button',{name:'Внести результат',exact:true}).click();await p.getByLabel('Комментарий',{exact:true}).fill('Сохранено в исходном плане');await save(p);},
      create:async p=>{await p.getByRole('button',{name:'Новая задача',exact:true}).click();await p.getByLabel('Название',{exact:true}).fill('Новая исходная задача');await save(p);},
      confirm:async p=>p.getByRole('button',{name:'Подтвердить план',exact:true}).click(),
      request:async p=>{await p.getByText('Ещё',{exact:true}).click();await p.getByRole('button',{name:'Изменить цель / время',exact:true}).click();await p.getByLabel('Предложенное значение').fill('20');await p.getByLabel('Причина',{exact:true}).fill('Тест согласования');await p.getByRole('button',{name:'Отправить запрос',exact:true}).click();},
      decision:async p=>{await p.getByRole('navigation').getByRole('button',{name:/Запросы/}).click();await p.getByRole('button',{name:'Утвердить',exact:true}).click();await p.getByRole('button',{name:'Планы',exact:true}).click();},
    };
    for(const name of Object.keys(operations)) for(const destination of ['date','employee']) {
      // Timer controls are manager-only; supervisor edit/create/approve/decision cover employee navigation.
      if(destination==='employee' && ['start','stop','confirm','request'].includes(name)) continue;
      await run(`A02 ${name}: switch ${destination}`,async()=>{
        const supervisor=destination==='employee'||name==='decision';
        const f=await fixture(browser,{supervisor:supervisor?901:undefined,prepare:s=>{if(name==='stop') s.plans[0].tasks[0].timer_started=1792047600;}});
        const g=gate();
        try {
          if(supervisor) await choose(f.page,1);
          await currentPlan(f.page,11);
          f.state.mutationHold=g.hold;
          const operation=name==='edit'&&supervisor?async p=>{await p.getByRole('button',{name:'Изменить',exact:true}).click();await p.getByLabel('Комментарий',{exact:true}).fill('Сохранено в исходном плане');await save(p);}:operations[name];
          await operation(f.page);await g.ready;
          // Close native modal only in this test to exercise otherwise possible programmatic navigation.
          await f.page.evaluate(()=>document.querySelector('dialog')?.close());
          await choose(f.page,destination==='employee'?2:undefined,destination==='date'?tomorrow:undefined);
          const expected=destination==='employee'?21:12;
          await currentPlan(f.page,expected);
          g.release();
          await f.page.getByRole('status').waitFor();
          await currentPlan(f.page,expected);
          assert.equal(await task(f.page,11).count(),0);
          assert.equal(await f.page.getByLabel('Дата плана',{exact:true}).inputValue(),destination==='date'?tomorrow:today);
          // Return: successful mutation persists in its original plan, never in destination.
          await choose(f.page,supervisor?1:undefined,today);await currentPlan(f.page,11);
          const original=f.state.plans[0], other=f.state.plans.find(p=>p.id===expected);
          if(name==='start') assert(original.tasks[0].timer_started);
          if(name==='stop') assert.equal(original.tasks[0].timer_started,null);
          if(name==='edit') {assert.equal(original.tasks[0].comment,'Сохранено в исходном плане');await f.page.getByText('Сохранено в исходном плане',{exact:true}).waitFor();}
          if(name==='create') {await f.page.getByRole('heading',{name:'Новая исходная задача',exact:true}).waitFor();assert.equal(other.tasks.length,1);}
          if(name==='confirm') {assert.equal(original.status,'approved');assert.equal(other.status,'draft');}
          if(name==='request') assert.equal(f.state.requests.length,2);
          if(name==='decision') assert.equal(f.state.requests[0].status,'approved');
          assert.equal(f.calls.filter(c=>c.method!=='GET').length,1,'mutation must never replay');
          assert(f.calls.filter(c=>c.path==='/plans').length<12,'no refresh render loop');
          assert.deepEqual(f.errors,[]);
        } finally {g.release();await f.close();}
      });
    }
    await run('A02 supervisor approval, navigate away and back before response',async()=>{
      const f=await fixture(browser,{supervisor:902}),g=gate();
      try {
        await choose(f.page,1);await currentPlan(f.page,11);f.state.mutationHold=g.hold;
        await f.page.getByRole('button',{name:'Утвердить план',exact:true}).click();await g.ready;
        await choose(f.page,2);await currentPlan(f.page,21);
        await choose(f.page,1);await currentPlan(f.page,11);
        g.release();await f.page.getByText('Подтверждён',{exact:true}).waitFor();assert.deepEqual(f.errors,[]);
      } finally {g.release();await f.close();}
    });
    for(const destination of ['empty','other-day','employee']) await run(`A10 error history -> ${destination}, retry and return`,async()=>{
      const f=await fixture(browser,{supervisor:destination==='employee'?901:undefined,prepare:s=>{s.historyError=true;if(destination==='empty')s.plans=s.plans.filter(p=>p.id!==12);}});
      try {
        if(destination==='employee') await choose(f.page,1);
        await currentPlan(f.page,11);
        const alert=f.page.getByRole('alert').filter({hasText:'История:'});await alert.waitFor();
        await choose(f.page,destination==='employee'?2:undefined,destination==='employee'?undefined:tomorrow);
        if(destination==='empty') await f.page.getByRole('button',{name:'Создать план',exact:true}).waitFor();else await currentPlan(f.page,destination==='employee'?21:12);
        assert.equal(await alert.count(),0);
        await choose(f.page,destination==='employee'?1:undefined,today);await currentPlan(f.page,11);await alert.waitFor();
        f.state.historyError=false;
        await alert.getByRole('button',{name:'Повторить загрузку'}).click();await alert.waitFor({state:'hidden'});
        await f.page.getByRole('button',{name:'История изменений',exact:true}).click();
        await f.page.getByText(/История плана 11/).waitFor();assert.deepEqual(f.errors,[]);
      } finally {await f.close();}
    });
    for(const fail of [false,true]) await run(`A10 late history ${fail?'error':'success'} ignored`,async()=>{
      const g=gate();
      const f=await fixture(browser,{prepare:s=>{s.historyError=fail;s.historyHold=id=>id===11?g.hold():Promise.resolve();}});
      try {
        await currentPlan(f.page,11);await g.ready;
        await choose(f.page,undefined,tomorrow);await currentPlan(f.page,12);
        await f.page.getByRole('button',{name:'История изменений',exact:true}).click();
        await f.page.getByText(/История плана 12/).waitFor();
        g.release();await f.page.waitForTimeout(150);
        assert.equal(await f.page.getByText(/История плана 11/).count(),0);
        assert.equal(await f.page.getByRole('alert').filter({hasText:'История:'}).count(),0);assert.deepEqual(f.errors,[]);
      } finally {g.release();await f.close();}
    });
    for(const [name,route,corrupt] of [
      ['workday','/me',v=>({...v,workday:{start:{bad:true},end:'19:00'}})],
      ['external URL','/plans/11',v=>({...v,tasks:[{...v.tasks[0],kind:'bitrix',external_url:{bad:true}}]})],
      ['unsafe URL','/plans/11',v=>({...v,tasks:[{...v.tasks[0],kind:'bitrix',external_url:'javascript:alert(1)'}]})],
      ['summary','/plans/11',v=>({...v,summary:{...v.summary,done:{bad:true}}})],
      ['historical snapshot','/plans/11/report',v=>({...v,initial_snapshot:{tasks:[{id:1,title:{bad:true},planned_minutes:10}]}})],
    ]) await run('A09 scoped malformed '+name,async()=>{
      const f=await fixture(browser,{prepare:s=>{
        if(route.endsWith('/report')) s.plans[0].status='closed';
        s.override=(p,m)=>{
          if(m!=='GET'||p!==route) return undefined;
          const value=p==='/me'?{user:employees[0],today,timezone:'Europe/Moscow',crm:{message:'Тест'}}:copy(s.plans[0]);
          return corrupt(value);
        };
      }});
      try {
        const message=f.page.getByText(/Сервер вернул данные в неожиданном формате/);
        await message.waitFor();
        assert.deepEqual(f.errors,[]);
        if(route!=='/me') {
          const alert=f.page.getByRole('alert').filter({hasText:'Планы:'});await alert.waitFor();
          assert.equal(await f.page.getByText('Загружаем планы…',{exact:true}).count(),0);
          f.state.override=null;
          await alert.getByRole('button',{name:'Повторить загрузку'}).click();await alert.waitFor({state:'hidden'});
          if(route.endsWith('/report')) await f.page.getByRole('heading',{name:'Итоговый отчёт'}).waitFor();else await currentPlan(f.page,11);
        }
      } finally {await f.close();}
    });
    await run('A09 legacy report, optional nulls and minimal historical snapshot',async()=>{
      const f=await fixture(browser,{prepare:s=>{const p=s.plans[0];p.status='closed';p.initial_snapshot={tasks:[{id:110,title:'Историческая задача',planned_minutes:10}]};delete p.tasks[0].external_url;delete p.tasks[0].distribution_target_locked;p.tasks[0].distribution_source=null;}});
      try {await f.page.getByRole('heading',{name:'Итоговый отчёт'}).waitFor();await f.page.getByText('Первоначальный утверждённый план',{exact:true}).click();await f.page.getByText('Историческая задача · 10 мин',{exact:true}).waitFor();assert.deepEqual(f.errors,[]);}
      finally {await f.close();}
    });
    await run('A02 well-formed detail for another plan is rejected',async()=>{
      const f=await fixture(browser,{prepare:s=>{s.override=(p,m)=>m==='GET'&&p==='/plans/11'?s.plans[2]:undefined;}});
      try {
        await f.page.getByRole('alert').filter({hasText:'Сервер вернул план другой даты или сотрудника'}).waitFor();
        assert.equal(await task(f.page,21).count(),0);
        assert.deepEqual(f.errors,[]);
      } finally {await f.close();}
    });
    console.log(`Audit regressions: ${passed} passed, ${failures.length} failed`);
    assert.deepEqual(failures,[]);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
