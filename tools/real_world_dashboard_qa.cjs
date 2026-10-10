// QA serves only saved real production results; it cannot initiate live work.
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),reports=path.join(root,'research/results/final_real_world_challenge');
const data=JSON.parse(fs.readFileSync(path.join(reports,'test1_live_stress.json'),'utf8'));
const output=path.join(reports,'dashboard_qa');fs.mkdirSync(output,{recursive:true});
const origin='http://127.0.0.1:18979';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--disable-background-networking']}),checks=[];
 try{
  for(const [name,width,height] of [['desktop',1440,1000],['ipad',834,1112],['phone',390,844]]){
   const context=await browser.newContext({viewport:{width,height},serviceWorkers:'block'}),page=await context.newPage();
   const errors=[],blocked=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
   page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
   await context.route('**/*',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(u.pathname.startsWith('/api/'))requests.push(u.pathname+u.search);
    if(u.origin!==origin||req.method()!=='GET'){blocked.push(u.pathname);return route.abort();}
    if((u.pathname==='/api/news'&&u.searchParams.get('symbol')!==data.symbol+'.NS')||
       (['/api/agents/result','/api/fusion'].includes(u.pathname)&&u.searchParams.get('id')!==data.snapshot_id)){
     blocked.push('Wrong snapshot/symbol: '+u.pathname);return route.abort();}
    const payloads={'/api/dashboard':data.dashboard,'/api/news':data.news,'/api/pipeline':data.pipeline,
     '/api/agents/result':data.cached_team,'/api/fusion':data.fusion,
     '/api/explanation':{status:'UNAVAILABLE'},'/api/symbol-search':{results:[]}};
    if(Object.hasOwn(payloads,u.pathname))return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payloads[u.pathname])});
    const file=path.resolve(root,'.'+u.pathname);
    if(!file.startsWith(path.join(root,'app')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
     blocked.push(u.pathname);return route.fulfill({status:404,body:''});}
    return route.fulfill({status:200,contentType:{'.html':'text/html','.css':'text/css','.js':'application/javascript'}[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
   });
   const capture=()=>page.evaluate(()=>({symbol:document.querySelector('#result-symbol').textContent,
    chartSymbol:document.querySelector('#chart-symbol').textContent,horizon:document.querySelector('#forecast-horizon').textContent,
    selectedHorizon:document.querySelector('input[name="forecast-horizon"]:checked').value,
    team:document.querySelector('#agent-status').textContent,
    roles:[...document.querySelectorAll('.agent-card')].map(c=>({agent:c.dataset.agent,status:c.querySelector('[data-role="status"]').textContent,
     facts:c.querySelector('[data-role="evidence"]').textContent,argument:c.querySelector('[data-role="argument"]').textContent})),
    fusion:document.querySelector('#fusion-view').textContent,fusionLineage:document.querySelector('#fusion-lineage').textContent,
    pipeline:document.querySelector('#pipeline-symbol').textContent,
    stages:[...document.querySelectorAll('.pipeline-stage')].map(c=>({stage:c.dataset.stage,status:c.querySelector('[data-role="status"]').textContent})),
    freshness:document.body.innerText.match(/Market closed[^\n]*/)?.[0]||'',
    overflow:document.documentElement.scrollWidth>innerWidth,
    privateContent:/(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Traceback|sk-proj-|tvly-|OPENAI_API_KEY|KRONOS_LAN_ACCESS_CODE/.test(document.body.innerText),
    canvasNonblank:[...document.querySelectorAll('canvas')].some(c=>{const p=c.getContext('2d')?.getImageData(0,0,c.width,c.height).data;return p&&p.some((v,i)=>i%4===3&&v>0);})}));
   const ready=()=>page.waitForFunction(()=>document.querySelector('#agent-status').textContent.includes('Saved analysis'));
   await page.goto(origin+'/app/dashboard.html');await ready();await page.waitForTimeout(300);const initial=await capture();
   await page.screenshot({path:path.join(output,name+'_overview.png')});
   await page.reload();await ready();await page.waitForTimeout(300);const reloaded=await capture();
   await page.locator('#agent-section').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,name+'_agents.png')});
   const pass=[initial,reloaded].every(v=>v.symbol.includes(data.symbol)&&v.chartSymbol.includes(data.symbol)&&
    v.horizon.includes('75')&&v.selectedHorizon==='75'&&v.pipeline.includes(data.symbol)&&
    v.fusion.toUpperCase()===data.fusion.view&&v.fusionLineage.includes(data.snapshot_id.slice(0,12))&&
    !v.overflow&&!v.privateContent&&v.canvasNonblank&&v.roles.length===3&&
    v.roles.every(r=>r.status==='Saved'&&(data.cached_team.agents[r.agent].report.action==='ABSTAIN'||r.facts.length>0))&&
    v.stages.every(s=>s.status===data.pipeline.stages[s.stage]?.status))&&errors.length===0&&blocked.length===0;
   checks.push({name,width,height,pass,initial,reloaded,errors,blocked,requests});await context.close();
  }
 }finally{await browser.close();}
 const report={status:checks.every(c=>c.pass)?'PASS':'FINDINGS',checks,external_calls:0,post_requests:0,
  scope:'Actual dashboard code with saved real BAJFINANCE OHLCV, forecast, news, agents, fusion and pipeline responses. Reload at desktop/iPad/phone sizes; no synthetic scaffold or additional provider requests. LAN auth independently tested.'};
 fs.writeFileSync(path.join(output,'qa.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({status:report.status,cases:checks.map(c=>({name:c.name,pass:c.pass,errors:c.errors,blocked:c.blocked,requests:c.requests}))}));
 if(report.status!=='PASS')process.exitCode=1;
})().catch(e=>{console.error('Saved-real-result browser QA failed: '+e.name);process.exitCode=1;});
