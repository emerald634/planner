// Execute the real TypeScript network client in memory; no server or credentials.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const assert = require('node:assert/strict');
function load(name, dependencies = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', name), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const module = {exports:{}};
  new Function('require','exports','module',code)(key=>dependencies[key],module.exports,module);
  return module.exports;
}
const validators = load('response.ts');
const {api} = load('api.ts',{'./response':validators});
const originalTimeout=global.setTimeout;
global.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms===15000?20:ms,...args);
global.window={Telegram:{WebApp:{initData:'synthetic-data'}}};
(async()=>{
  try {
    global.fetch=async()=>new Response(JSON.stringify([]));
    assert.deepEqual(await api('/employees'),[]);
    global.fetch=async()=>new Response(JSON.stringify({wrong:[]}));
    await assert.rejects(api('/employees'),/неожиданном формате/);
    global.fetch=async()=>new Response('not json');
    await assert.rejects(api('/plans'),/некорректный JSON/);
    global.fetch=async()=>new Response(JSON.stringify({detail:'Ошибка проверки'}),{status:403});
    await assert.rejects(api('/requests'),/Ошибка проверки/);
    global.fetch=async()=>{throw Error('private transport details');};
    await assert.rejects(api('/plans'),/Нет связи/);
    let signal;
    global.fetch=(_,options)=>{signal=options.signal;return new Promise(()=>{});};
    await assert.rejects(api('/distributions'),/15 секунд/);
    assert.equal(signal.aborted,true);
    global.fetch=async()=>({ok:true,status:200,json:()=>new Promise(()=>{})});
    await assert.rejects(api('/distributions'),/15 секунд/);
    global.fetch=async()=>({ok:false,status:500,json:()=>new Promise(()=>{})});
    await assert.rejects(api('/requests'),/15 секунд/);
    let mutations=0;
    global.fetch=async()=>{mutations++;return new Promise(()=>{});};
    await assert.rejects(api('/tasks/1','PATCH',{revision:1,comment:'test'}),/Изменение могло сохраниться/);
    assert.equal(mutations,1,'timed out mutations must not replay');
    validators.validateResponse('/distributions','GET',[{id:'x',employee_name:'Система',status:'error',reason:'import_retry',count:null,dates:[]}]);
    assert.throws(()=>validators.validateResponse('/me','GET',{user:{role:'supervisor'}}),/формате/);
    assert.throws(()=>validators.validateResponse('/distributions','GET',[{id:'x',status:'review'}]),/формате/);
    assert.throws(()=>validators.validateResponse('/plans/1','GET',{tasks:[]}),/формате/);
    const employee={id:1,name:'Synthetic',role:'manager',active:1,telegram_id:null,bitrix_id:null};
    const me={user:employee,today:'2026-10-15',timezone:'Europe/Moscow',crm:{message:'Synthetic',connected:false}};
    const workday={start:'10:00',end:'19:00',timezone:'Europe/Moscow',reminders_enabled:false};
    const task={id:10,plan_id:1,employee_id:1,title:'Test',description:'',comment:'',result:'',planned_minutes:0,actual_value:0,actual_seconds:0,revision:1,locked:0,kind:'quantitative',status:'todo',target:null,timer_started:null};
    const plan={id:1,employee_id:1,employee_name:'Synthetic',day:'2026-10-15',status:'closed',summary:{total:1,done:0,moved:0,planned_minutes:0,actual_seconds:0},tasks:[task],server_time:1};
    function valid(route,value) {assert.doesNotThrow(()=>validators.validateResponse(route,'GET',value));}
    function invalid(route,value) {assert.throws(()=>validators.validateResponse(route,'GET',value),/неожиданном формате/);}
    valid('/me',me);valid('/me',{...me,workday});valid('/me',{...me,workday:null});
    for(const [key,values] of Object.entries({start:[{},null,10,'25:00'],end:[[],false,'19:99'],timezone:[{},null],reminders_enabled:[{},0,'false']}))
      for(const value of values) invalid('/me',{...me,workday:{...workday,[key]:value}});
    invalid('/me',{...me,crm:{message:{}}});invalid('/me',{...me,crm:{message:'Test',connected:'false'}});
    for(const value of [{},[],false,'101']) invalid('/employees',[{...employee,telegram_id:value}]);
    valid('/plans/1/report',plan);
    valid('/plans/1/report',{...plan,initial_snapshot:null});
    valid('/plans/1/report',{...plan,initial_snapshot:{tasks:[{id:1,title:'Legacy',planned_minutes:10}]}});
    for(const value of [null,{},[],0]) invalid('/plans/1/report',{...plan,initial_snapshot:{tasks:[{id:1,title:value,planned_minutes:10}]}});
    for(const key of Object.keys(plan.summary)) invalid('/plans/1',{...plan,summary:{...plan.summary,[key]:{bad:true}}});
    for(const value of [null,'https://example.test/task/1','http://example.test/legacy']) valid('/plans/1',{...plan,tasks:[{...task,external_url:value}]});
    for(const value of [{},10,'bad URL','javascript:alert(1)','data:text/html,x','https://user:pass@example.test/']) invalid('/plans/1',{...plan,tasks:[{...task,external_url:value}]});
    valid('/plans/1',{...plan,tasks:[{...task,distribution_source:null}]});
    valid('/plans/1',{...plan,tasks:[{...task,distribution_source:{name:'Утреннее распределение',count:3,dates:['2026-10-14']}}]});
    invalid('/plans/1',{...plan,tasks:[{...task,distribution_source:{name:{},count:3,dates:[]}}]});
    invalid('/plans/1',{...plan,tasks:[{...task,distribution_source:{name:'Test',count:3,dates:[null]}}]});
    invalid('/plans/1',{...plan,tasks:[{...task,distribution_target_locked:{}}]});
    invalid('/plans/1',{...plan,tasks:[{...task,elapsed_seconds:{}}]});
    const request={id:1,task_id:10,employee_name:'Synthetic',title:'Test',reason:'',decision_comment:'',day:'2026-10-15',field:'target',status:'pending',proposed:1,old_value:null};
    valid('/requests',[request]);valid('/requests',[{...request,decided_at:null}]);
    invalid('/requests',[{...request,decided_at:{}}]);invalid('/requests',[{...request,decision_comment:{}}]);
    const history={id:1,created_at:1,actor_name:'Synthetic',action:'task_updated',entity:'task',entity_id:10,before_json:null,after_json:{comment:{arbitrary:'audit values are safely stringified'}}};
    valid('/plans/1/history',[history]);invalid('/plans/1/history',[{...history,after_json:[]}]);
    console.log('PASS: A09 nested data, workday, links, summaries, legacy reports/snapshots, optional/null values; no mutation retries.');
    console.log('PASS: hotfix API validation, HTTP/network errors, timeout including success/error JSON bodies and AbortSignal.');
  } finally {global.setTimeout=originalTimeout;}
})().catch(error=>{console.error(error);process.exitCode=1;});
