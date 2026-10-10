// Report-only saved live failure QA; no provider calls or privileged actions.
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),reports=path.join(root,'research/results/healthcheck_postrepair');
const data=JSON.parse(fs.readFileSync(path.join(reports,'v3_live_browser_fixture.json'),'utf8'));
const output=path.join(reports,'v3_live_qa');fs.mkdirSync(output,{recursive:true});
const origin='http://127.0.0.1:18976';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--disable-background-networking']}),checks=[];
 try{
  for(const test of ['A','B']){
   const outcome=data.outcomes[test],fixture=JSON.parse(JSON.stringify(data.fixture));
   fixture.news.evidence_snapshot_id=outcome.cached_team.snapshot_id;
   fixture.pipeline.stages.agents=outcome.health;
   fixture.pipeline.stages.fusion=outcome.fusion_health;
   for(const [name,width,height] of [['desktop',1440,1000],['phone',390,844],['ipad',834,1112]]){
    const context=await browser.newContext({viewport:{width,height},serviceWorkers:'block'}),page=await context.newPage();
    const errors=[],blocked=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    await context.route('**/*',async route=>{
     const req=route.request(),u=new URL(req.url());
     if(u.origin!==origin||req.method()!=='GET'){blocked.push(u.pathname);return route.abort();}
     const payloads={'/api/dashboard':fixture.dashboard,'/api/news':fixture.news,'/api/pipeline':fixture.pipeline,
      '/api/agents/result':outcome.cached_team,'/api/fusion':outcome.fusion,'/api/explanation':{status:'UNAVAILABLE'},'/api/symbol-search':{results:[]}};
     if(Object.hasOwn(payloads,u.pathname))return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payloads[u.pathname])});
     const file=path.resolve(root,'.'+u.pathname);
     if(!file.startsWith(path.join(root,'app')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
      blocked.push(u.pathname);return route.fulfill({status:404,body:''});}
     return route.fulfill({status:200,contentType:{'.html':'text/html','.css':'text/css','.js':'application/javascript'}[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
    });
    const capture=()=>page.evaluate(()=>({team:document.querySelector('#agent-status').textContent,
     roles:[...document.querySelectorAll('.agent-card')].map(c=>({agent:c.dataset.agent,status:c.querySelector('[data-role="status"]').textContent,
      argument:c.querySelector('[data-role="argument"]').textContent,facts:c.querySelector('[data-role="evidence"]').textContent,confidence:c.querySelector('[data-role="confidence"]').textContent})),
     overflow:document.documentElement.scrollWidth>innerWidth,
     privateContent:/(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Traceback|sk-proj-|tvly-|OPENAI_API_KEY|KRONOS_LAN_ACCESS_CODE/.test(document.body.innerText),
     agentPipeline:document.querySelector('.pipeline-stage[data-stage="agents"]').textContent,
     fusionLineage:document.querySelector('#fusion-lineage').textContent,
     canvasNonblank:[...document.querySelectorAll('canvas')].some(c=>{const d=c.getContext('2d')?.getImageData(0,0,c.width,c.height).data;return d&&d.some((v,i)=>i%4===3&&v>0);})}));
    await page.goto(origin+'/app/dashboard.html');
    await page.waitForFunction(()=>document.querySelector('#agent-status')?.textContent.includes('No accepted team result'));
    await page.waitForTimeout(300);const initial=await capture();
    await page.reload();await page.waitForFunction(()=>document.querySelector('#agent-status')?.textContent.includes('No accepted team result'));
    await page.waitForTimeout(300);const reloaded=await capture();
    await page.locator('#agent-section').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,test+'_'+name+'.png')});
    const pass=[initial,reloaded].every(v=>!v.overflow&&!v.privateContent&&v.canvasNonblank&&v.roles.length===3&&
     v.roles.every(r=>r.status==='Failed'&&r.facts===''&&r.confidence==='')&&v.agentPipeline.includes('FAILED')&&
     v.fusionLineage.includes(outcome.cached_team.snapshot_id.slice(0,12)))&&errors.length===0&&blocked.length===0;
    checks.push({test,name,width,height,pass,initial,reloaded,errors,blocked});await context.close();
   }
  }
 }finally{await browser.close();}
 const report={status:checks.every(v=>v.pass)?'PASS':'FINDINGS',checks,external_calls:0,post_requests:0,
  scope:'Real retained v3 failure states, empty rejected facts/confidence, safe messages, persisted reload, correct fusion/agent snapshot. Saved synthetic chart base; no live market or LAN claim. Accepted v3 adapter remains unproven live.'};
 fs.writeFileSync(path.join(output,'qa.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({status:report.status,cases:checks.map(v=>({test:v.test,name:v.name,pass:v.pass,errors:v.errors,blocked:v.blocked,overflow:v.initial.overflow}))}));
 if(report.status!=='PASS')process.exitCode=1;
})().catch(e=>{console.error(e.message);process.exitCode=1;});
