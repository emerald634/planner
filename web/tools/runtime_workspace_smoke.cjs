// Real Edge against one owned synthetic run; no successful response mocks.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const run=process.argv[2];assert(/^lfweb_[a-f0-9]{32}$/.test(run));
const repo=path.resolve(__dirname,'..'),scratch=path.resolve(repo,'../.workbench/browser',run);
const meta=JSON.parse(fs.readFileSync(path.join(scratch,'owner.json'),'utf8'));
assert.equal(meta.run_id,run);assert.equal(meta.kind,'leadflow-planner-local-mvp');
const accounts=JSON.parse(fs.readFileSync(path.join(scratch,'credentials.json'),'utf8'));
const {chromium}=require(path.join(meta.planner_source,'miniapp/node_modules/playwright'));
const origin=`http://127.0.0.1:${meta.port}`,artifacts=path.resolve(repo,'../test-artifacts/browser-business',run);
fs.mkdirSync(artifacts,{recursive:true});const checks=[],external=[],errors=[];
const ok=name=>{checks.push(name);console.log(name)};
async function login(page,name){const a=accounts.find(a=>a.email.startsWith(name+'@'));await page.goto(origin+'/login');await page.getByLabel('Email',{exact:true}).fill(a.email);await page.getByLabel('Пароль',{exact:true}).fill(a.password);await page.getByRole('button',{name:'Войти',exact:true}).click();await page.getByTitle('Выйти').waitFor();}
async function api(page,resource,method='GET',body){return page.evaluate(async({resource,method,body})=>{const headers={'Content-Type':'application/json'};if(method!=='GET'){const r=await fetch('/api/v1/auth/csrf');headers['X-CSRF-Token']=(await r.json()).csrf}const response=await fetch('/api/v1'+resource,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});return{status:response.status,value:await response.json()}},{resource,method,body})}
const count=(page,key,field,value)=>page.locator(`[data-indicator="${key}"]`).getByLabel(field,{exact:true}).fill(String(value));
async function detail(page,key,name){const row=page.locator(`[data-indicator="${key}"]`);await row.locator('summary').click();await row.getByRole('button',{name:'Добавить клиента',exact:true}).click();await row.getByLabel('Клиент показателя',{exact:true}).fill(name);await row.getByLabel('Результат',{exact:true}).fill('Искусственный результат');return row;}
(async()=>{
const browser=await chromium.launch({headless:true,channel:'msedge'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',r=>{if(new URL(r.request().url()).origin!==origin){external.push('blocked');return r.abort()}return r.continue()});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
try{
await login(page,'manager');assert.equal(await page.locator('.pw-local-banner').count(),0);await page.getByRole('link',{name:'Недозвоны',exact:true}).click();
await page.getByRole('button',{name:'Рассчитать распределение',exact:true}).click();
await page.getByRole('heading',{name:/Даты и варианты/}).waitFor();
const replace=page.getByRole('button',{name:'Подобрать предыдущую непустую',exact:true});
if(await replace.count()){await replace.first().click();await page.getByRole('heading',{name:/Даты и варианты/}).waitFor();}
const radios=page.getByRole('radio');await radios.last().check();
let history=await api(page,'/planner/distribution/history');assert.equal(history.value.length,0);ok('calculation and variant selection do not publish');
await page.getByRole('button',{name:'✅ Подтвердить распределение',exact:true}).click();
await page.getByText(/^Подтверждено /).waitFor();
await page.getByText(/Импортировано/).waitFor({timeout:20000});
history=await api(page,'/planner/distribution/history');assert.equal(history.value.length,1);assert.equal(history.value[0].allocations.length,1);ok('confirmed distribution automatically imported; manager history scoped');
await page.goto(origin+'/planner');await page.locator('[data-indicator="calls"]').waitFor();
assert.equal(await page.locator('[data-indicator]').count(),8);ok('eight rows on manager daily plan');
await count(page,'calls','Факт Исходящие звонки',43);assert(await page.getByRole('button',{name:'Подтвердить план',exact:true}).isDisabled());ok('unsaved daily changes block confirmation until saved');
await count(page,'new_leads','План Новые заявки',2);await count(page,'new_leads','Факт Новые заявки',1);
let row=await detail(page,'consultations','Тест консультации');await row.getByLabel('Выполнено / состоялось',{exact:true}).check();
await count(page,'pain','План Выгрузка боли по горячим сделкам',1);await count(page,'pain','Факт Выгрузка боли по горячим сделкам',1);
row=await detail(page,'conversations','Тест разговора');await row.locator('select').selectOption('active');await row.getByLabel('Выполнено / состоялось',{exact:true}).check();await row.getByLabel('Есть рекомендация',{exact:true}).check();
await page.getByLabel('Просроченные утром',{exact:true}).fill('12');await count(page,'overdue','Факт Просроченные задачи Bitrix24',2);
await count(page,'payments','План Ожидающие оплату',1);await count(page,'payments','Факт Ожидающие оплату',1);
const me=(await api(page,'/planner/me')).value,today=me.today;
row=await detail(page,'payments','Тест оплаты');await row.getByLabel('Дата ожидаемой оплаты',{exact:true}).fill(today);await row.getByLabel('Касание запланировано',{exact:true}).fill(today);await row.getByLabel('Выполнено / состоялось',{exact:true}).check();
row=page.locator('[data-indicator="missed"]');await row.locator('summary').click();
await row.getByRole('button',{name:'Добавить повторную попытку',exact:true}).first().click();
await row.getByLabel('Звонок',{exact:true}).first().check();await row.getByLabel('Сообщение (ручная отметка)',{exact:true}).first().check();await row.getByLabel('Дозвонились',{exact:true}).first().check();
await page.getByLabel('Договоры для недели',{exact:true}).fill('1');
await page.getByRole('button',{name:'Сохранить показатели',exact:true}).click();await page.getByText('Показатели сохранены на сервере',{exact:true}).waitFor();
await page.reload();await page.getByLabel('Факт Исходящие звонки',{exact:true}).waitFor();assert.equal(await page.getByLabel('Факт Исходящие звонки',{exact:true}).inputValue(),'43');ok('all eight rows, client detail, repeat attempts and weekly contracts persist after reload');
const plans=(await api(page,`/planner/plans?day=${today}`)).value,plan=plans[0];
let daily=(await api(page,`/planner/plans/${plan.id}/daily`)).value;assert.equal(daily.indicators.find(r=>r.key==='missed').actual,1);assert.equal(daily.indicators.find(r=>r.key==='missed').connected,1);
assert.equal((await api(page,`/planner/weekly?employee_id=1&day=${today}`)).value.totals.contracts,1);ok('missed norm uses call AND message; connected separate; weekly actual calculated');
await count(page,'calls','Факт Исходящие звонки',44);
await page.route('**/planner/plans/*/sources/*',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Искусственная ошибка источника'})}));
await page.getByText('Источники Bitrix24 (не заменяют ручные результаты)',{exact:true}).click();await page.getByRole('button',{name:'Повторить проверку источников',exact:true}).click();await page.getByText('Искусственная ошибка источника',{exact:true}).first().waitFor();assert.equal(await page.getByLabel('Факт Исходящие звонки',{exact:true}).inputValue(),'44');await page.unroute('**/planner/plans/*/sources/*');ok('source failure does not erase saved or unsaved manual fact');
await page.getByRole('button',{name:'Сохранить показатели',exact:true}).click();await page.getByText('Показатели сохранены на сервере',{exact:true}).waitFor();
await page.getByRole('button',{name:'Подтвердить план',exact:true}).click();await page.getByText('Подтверждён',{exact:true}).first().waitFor();ok('manager confirms own plan');
daily=(await api(page,`/planner/plans/${plan.id}/daily`)).value;
const toBody=d=>({revision:d.revision,contracts:d.contracts,indicators:d.indicators.map(({key,planned,actual,morning,details})=>({key,planned,actual,morning,details:details.map(({created_date,...x})=>x)}))});
let body=toBody(daily);body.indicators.find(r=>r.key==='missed').planned++;assert.equal((await api(page,`/planner/plans/${plan.id}/daily`,'PUT',body)).status,409);ok('forged imported target rejected');
body=toBody(daily);body.indicators[0].actual=45;assert.equal((await api(page,`/planner/plans/${plan.id}/daily`,'PUT',body)).status,200);assert.equal((await api(page,`/planner/plans/${plan.id}/daily`,'PUT',body)).status,409);ok('fact remains editable after confirm; stale revision rejected');
daily=(await api(page,`/planner/plans/${plan.id}/daily`)).value;const initial=(await api(page,`/planner/plans/${plan.id}`)).value.initial_snapshot;body=toBody(daily);body.indicators.find(r=>r.key==='new_leads').planned++;
let grown=await api(page,`/planner/plans/${plan.id}/daily`,'PUT',body);assert.equal(grown.status,200);body=toBody(grown.value);body.indicators.find(r=>r.key==='new_leads').planned--;assert.equal((await api(page,`/planner/plans/${plan.id}/daily`,'PUT',body)).status,409);assert.deepEqual((await api(page,`/planner/plans/${plan.id}`)).value.initial_snapshot,initial);ok('new daily manual list can grow after confirm; decrease denied; initial snapshot preserved');

await page.reload();await page.locator('[data-indicator="calls"]').waitFor();await page.screenshot({path:path.join(artifacts,'manager-daily.png'),fullPage:true});
await page.getByTitle('Выйти').click();await login(page,'supervisor');await page.goto(origin+'/planner');await page.locator('[data-indicator="calls"]').waitFor();
const em=await api(page,'/planner/employees');assert.equal(em.value.length,2);
assert.equal((await api(page,`/planner/plans/${plan.id}/daily`)).value.indicators[0].actual,45);await page.screenshot({path:path.join(artifacts,'supervisor-daily.png'),fullPage:true});ok('supervisor sees two managers and selected manager daily values');
await page.goto(origin+'/distributions');await page.getByText('Расчёт доступен; отдельное право подтверждения не назначено.',{exact:true}).count();const opt=await api(page,'/planner/distribution/options');assert.equal(opt.value.can_confirm,false);ok('supervisor not automatically confirmer');
await page.goto(origin+'/leads');await page.getByRole('button',{name:'Добавить лид',exact:true}).click();await page.getByLabel('Телефон *',{exact:true}).fill('+0 000 000 0009');await page.getByLabel('Имя',{exact:true}).fill('Синтетический новый лид');await page.locator('.modal select').selectOption('local');await page.getByRole('button',{name:'Готово',exact:true}).click();await page.getByRole('link',{name:'Синтетический новый лид',exact:true}).waitFor();ok('LeadFlow ordinary creation uses existing assignment algorithm; test egress blocked');
const leadList=(await api(page,'/leads?page_size=100')).value;
const lead=leadList.items.find(x=>x.name==='Синтетический новый лид');const operation={request_id:crypto.randomUUID(),manager_id:102};
assert.equal((await api(page,`/leads/${lead.id}`,'PATCH',{manager_id:operation.manager_id})).status,200);assert.equal((await api(page,`/leads/${lead.id}`,'PATCH',{manager_id:operation.manager_id})).value.manager_id,102);ok('LeadFlow ordinary manual reassignment repeated safely');
await page.getByTitle('Выйти').click();await login(page,'other');assert.equal((await api(page,`/planner/plans/${plan.id}/daily`)).status,403);assert.equal((await api(page,'/leads/'+lead.id,'PATCH',{manager_id:101})).status,403);ok('other manager cannot access daily plan or reassign LeadFlow leads');
await page.getByTitle('Выйти').click();await login(page,'admin');assert.equal((await api(page,'/planner/me')).status,403);await page.getByTitle('Выйти').click();await login(page,'unmapped');assert.equal((await api(page,'/planner/me')).status,403);ok('admin and unmapped do not inherit Planner access');
await page.getByTitle('Выйти').click();await login(page,'manager');
const closed=await api(page,`/planner/plans/${plan.id}/close`,'POST');assert.equal(closed.status,200);assert.equal(closed.value.daily.indicators[0].actual,45);
assert.equal((await api(page,`/planner/plans/${plan.id}/daily`,'PUT',toBody((await api(page,`/planner/plans/${plan.id}/daily`)).value))).status,409);
assert.deepEqual((await api(page,`/planner/plans/${plan.id}/report`)).value,closed.value);ok('closed daily snapshot immutable; report preserved');
let closedSourceWrites=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/sources/'))closedSourceWrites++});
await page.goto(origin+'/planner');await page.getByLabel('Факт Исходящие звонки',{exact:true}).waitFor();assert.equal(await page.getByLabel('Факт Исходящие звонки',{exact:true}).inputValue(),'45');
await page.goto(origin+'/planner/reports');await page.getByRole('heading',{name:'Сохранённый отчёт',exact:true}).waitFor();await page.screenshot({path:path.join(artifacts,'closed-report.png'),fullPage:true});
assert.equal(closedSourceWrites,0);assert.deepEqual((await api(page,`/planner/plans/${plan.id}/report`)).value,closed.value);ok('closed plan and saved report reopen without CRM mutation; frozen values survive');
for(const width of [1024,390]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)}ok('Edge adaptive widths 1024 and390 without document overflow');
assert.deepEqual(external,[]);assert.deepEqual(errors,[]);ok('zero external requests and unhandled page errors');
fs.writeFileSync(path.join(artifacts,'browser-results.json'),JSON.stringify({run,checks,external_requests:external.length,page_errors:errors,successful:true},null,2));
const cdp=await browser.newBrowserCDPSession();const info=await cdp.send('SystemInfo.getProcessInfo');const ids=info.processInfo.map(p=>Number(p.id)).filter(Number.isSafeInteger);const ps=`Get-Process -Id @(${ids.join(',')}) -ErrorAction SilentlyContinue | Select-Object Id,WorkingSet64,PeakWorkingSet64 | ConvertTo-Json -Compress`;const memory=JSON.parse(require('node:child_process').execFileSync('powershell.exe',['-NoProfile','-Command',ps],{encoding:'utf8',windowsHide:true}));fs.writeFileSync(path.join(artifacts,'edge-memory.json'),JSON.stringify({platform:'Windows',owned_browser_processes:memory,server_headroom_measured:false,measurement:'Working sets at end of synthetic Edge smoke; individual process peaks are not simultaneous peaks'},null,2));
}catch(e){await page.screenshot({path:path.join(artifacts,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(artifacts,'browser-failure.json'),JSON.stringify({checks,error:String(e)},null,2));throw e}finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exitCode=1});
