// Read-only synthetic dashboard server for native gstack QA; no provider implementation is imported.
const fs=require('fs'),path=require('path'),http=require('http');
const root=path.resolve(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,
 'research/results/healthcheck_postrepair/v3_typed_prose_browser_fixture.json'),'utf8'));
let test='A';
http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1:18976');
 res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-src 'none'");
 res.setHeader('Cache-Control','no-store');
 if(req.method!=='GET'){res.writeHead(405);return res.end();}
 if(url.pathname==='/app/dashboard.html')test=url.searchParams.get('offline_test')==='B'?'B':'A';
 const outcome=data.outcomes[test],fixture=JSON.parse(JSON.stringify(data.fixture));
 fixture.news.evidence_snapshot_id=outcome.cached_team.snapshot_id;
 fixture.pipeline.stages.agents=outcome.health;
 fixture.pipeline.stages.fusion={status:'HEALTHY',rows:outcome.fusion.evidence_items.length,warnings:[],errors:[]};
 const payloads={'/api/dashboard':fixture.dashboard,'/api/news':fixture.news,'/api/pipeline':fixture.pipeline,
  '/api/agents/result':outcome.cached_team,'/api/fusion':outcome.fusion,
  '/api/explanation':{status:'UNAVAILABLE'},'/api/symbol-search':{results:[]}};
 if(Object.hasOwn(payloads,url.pathname)){res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(payloads[url.pathname]));}
 const file=path.resolve(root,'.'+url.pathname);
 if(!file.startsWith(path.join(root,'app')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
  res.writeHead(404);return res.end();
 }
 res.writeHead(200,{'Content-Type':{'.html':'text/html','.css':'text/css','.js':'application/javascript'}[path.extname(file)]||'application/octet-stream'});
 res.end(fs.readFileSync(file));
}).listen(18976,'127.0.0.1',()=>console.log('Offline synthetic dashboard ready on loopback only; mutations blocked.'));
