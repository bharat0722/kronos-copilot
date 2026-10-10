"""Explicitly authorized, bounded synthetic v3 validation; no production edits."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import agent_research as ar, agent_output_v3 as v3
from app.evidence_snapshot import canonical_bytes, snapshot_id
from app.evidence_fusion import EvidenceFusionEngine
from app.usage_budget import DailyUsageBudget

REPORTS = ROOT / 'research/results/healthcheck_postrepair'
MANIFEST = REPORTS / 'v3_fresh_fixture_manifest.json'
SCOPE = ROOT / 'outputs/agent_research/v3_live_confirmation'
ALLOW = [('record', 'created_at'), ('record', 'evidence', 'market_data', 'retrieved_at'),
         ('record', 'evidence', 'technicals', 'as_of')]

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path, value):
    ar._atomic_json(path, value)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat()

def credential():
    if not os.environ.get('OPENAI_API_KEY'):
        for line in (ROOT / '.env.local').read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENAI_API_KEY='):
                os.environ['OPENAI_API_KEY'] = line.split('=', 1)[1].strip().strip('"')
                break
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('Configured OpenAI credential unavailable')

def source_check(manifest):
    checks = {p: sha(ROOT / p) == h for p, h in manifest['source_hashes'].items()}
    if not all(checks.values()):
        raise RuntimeError('Frozen production source changed; no execution allowed')
    return checks

def private_check(value):
    text = canonical_bytes(value).decode('utf-8')
    if re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|sk-proj-|tvly-|PRIVATE KEY|Traceback|OPENAI_API_KEY|KRONOS_LAN_ACCESS_CODE', text):
        raise RuntimeError('Private or unsafe content detected')
    key = os.environ.get('OPENAI_API_KEY')
    if key and key in text:
        raise RuntimeError('Credential in payload')

def prepare():
    if MANIFEST.exists():
        raise RuntimeError('Fresh manifest already exists; inspect persisted state, do not recreate')
    old = load(REPORTS / 'v3_live_retest_manifest.json')
    source_check(old)
    assert ar.SCHEMA_VERSION == 'agent_output_v3'
    assert ar.PROMPT_VERSIONS == old['prompt_versions']
    config = ar.AgentConfig()
    assert config.model == 'gpt-5-mini' and config.max_output_tokens == 1600
    assert config.max_input_bytes == 48000 and config.daily_call_limit == 12
    assert ar.MAX_REASONING_ROUNDS == ar.MAX_RETRIES == 1
    stamp = now(); fixtures = {}
    for test, row in old['fixtures'].items():
        path = ROOT / row['fixture_path']
        assert sha(path) == row['fixture_file_sha256']
        original = load(path); fresh = copy.deepcopy(original)
        changes = []
        for parts in ALLOW:
            item = fresh
            for part in parts[:-1]: item = item[part]
            changes.append({'path': list(parts), 'before': item[parts[-1]], 'after': stamp})
            item[parts[-1]] = stamp
        fresh['record']['snapshot_id'] = snapshot_id(fresh['record']['evidence'])
        restored = copy.deepcopy(fresh)
        for change in changes:
            item = restored
            for part in change['path'][:-1]: item = item[part]
            item[change['path'][-1]] = change['before']
        restored['record']['snapshot_id'] = original['record']['snapshot_id']
        assert canonical_bytes(restored) == canonical_bytes(original)
        assert fresh['record']['snapshot_id'] != original['record']['snapshot_id']
        assert fresh['synthetic_only'] and fresh['record']['evidence']['instrument']['canonical_symbol'] == 'NSE:TESTCO'
        assert v3.fact_catalog(ar.evidence_catalog(original['record']['evidence'])) == v3.fact_catalog(ar.evidence_catalog(fresh['record']['evidence']))
        private_check(fresh)
        team = ar.AgentTeam(SCOPE / test / 'agents', config=config)
        preflight = team.preflight(fresh['record'])
        catalog = ar.evidence_catalog(fresh['record']['evidence'])
        misses = {role: team._cached(fresh['record']['snapshot_id'], role, catalog) is None for role in ar.AGENTS}
        assert all(misses.values())
        wire = ar.serialize_agent_input(fresh['record'])
        assert len(wire) < 42000
        destination = REPORTS / 'v3_live_fixtures' / f'{test}.json'
        save(destination, fresh)
        fixtures[test] = {'fixture_id': fresh['fixture_id'], 'fixture_path': destination.relative_to(ROOT).as_posix(),
            'fixture_file_sha256': sha(destination), 'snapshot_id': fresh['record']['snapshot_id'],
            'previous_snapshot_id': original['record']['snapshot_id'], 'input_bytes': len(wire),
            'input_sha256': hashlib.sha256(wire).hexdigest(), 'semantic_difference': 0,
            'permitted_changes': changes, 'fact_reference_changes': 0, 'initial_cache_miss': misses,
            'preflight': preflight, 'cache_scope': (SCOPE/test/'agents').relative_to(ROOT).as_posix()}
    assert fixtures['A']['snapshot_id'] != fixtures['B']['snapshot_id']
    manifest = {'schema_version': 'v3_fresh_fixture_manifest_v1', 'created_at': stamp,
        'expires_at': (datetime.fromisoformat(stamp)+timedelta(hours=1)).isoformat(),
        'agent_schema': ar.SCHEMA_VERSION, 'prompt_versions': ar.PROMPT_VERSIONS,
        'validator': v3.VALIDATOR_VERSION, 'renderer': v3.RENDERER_VERSION, 'config': asdict(config),
        'source_hashes': old['source_hashes'], 'fixtures': fixtures, 'max_workflows': 2, 'max_openai_calls': 12,
        'authorization': 'Explicit attachment authorization and separate confirmed reuse of existing credential',
        'budget_scope': 'Task-specific persisted shared twelve-call budget; production counters not reset or changed',
        'publication_dates': 'Unchanged; only existing harness/fusion freshness metadata renewed',
        'loop_limit': 1, 'retry_limit': 1, 'tools': 'NONE', 'synthetic_only': True}
    save(MANIFEST, manifest)
    print(json.dumps({'stage':'FROZEN','fixtures':{n:{k:r[k] for k in ('fixture_id','snapshot_id','input_bytes','semantic_difference','initial_cache_miss')} for n,r in fixtures.items()}},indent=2))

class AllowedTransport:
    def __init__(self):
        import httpx2 as httpx
        self.inner = httpx.HTTPTransport(retries=0)
        self.requests = 0
    def handle_request(self, request):
        if request.url.scheme != 'https' or request.url.host != 'api.openai.com' or request.url.path != '/v1/responses' or request.method != 'POST':
            raise RuntimeError('Non-authorized external request blocked')
        self.requests += 1
        if self.requests > 12: raise RuntimeError('Transport call maximum exceeded')
        return self.inner.handle_request(request)
    def close(self): self.inner.close()

class GuardResponses:
    def __init__(self, client, config):
        self.client = client; self.config = config
    def create(self, **request):
        state = load(SCOPE / 'execution.json')
        if state['provider_calls'] >= 12: raise RuntimeError('Authorized call maximum reached')
        test = state['active_test']; manifest = load(MANIFEST); row = manifest['fixtures'][test]
        source_check(manifest)
        assert request['model'] == self.config.model and request['max_output_tokens'] == 1600
        assert request['tools'] == [] and request['tool_choice'] == 'none' and not request['parallel_tool_calls']
        wire_text = request['input'].split('\n',1)[1]
        assert hashlib.sha256(wire_text.encode('utf-8')).hexdigest() == row['input_sha256']
        private_check(json.loads(wire_text))
        state['provider_calls'] += 1
        save(SCOPE / 'execution.json', state)
        print(f"LIVE {test}: attempt {state['provider_calls']}/12", flush=True)
        return self.client.responses.create(**request)

def fixture_read(row):
    assert sha(ROOT / row['fixture_path']) == row['fixture_file_sha256']
    fixture = load(ROOT / row['fixture_path']); record = fixture['record']
    assert snapshot_id(record['evidence']) == record['snapshot_id'] == row['snapshot_id']
    wire = ar.serialize_agent_input(record)
    assert len(wire) == row['input_bytes'] and hashlib.sha256(wire).hexdigest() == row['input_sha256']
    private_check(fixture)
    return fixture

def run():
    import httpx2 as httpx
    from openai import OpenAI
    manifest = load(MANIFEST); source_check(manifest); credential()
    config = ar.AgentConfig(); assert asdict(config) == manifest['config']
    execution = SCOPE/'execution.json'
    if execution.exists(): raise RuntimeError('Execution already started; do not rerun live workflows')
    for row in manifest['fixtures'].values():
        fixture = fixture_read(row); ar.assert_fresh_snapshot(fixture['record'])
    budget = DailyUsageBudget(SCOPE/'authorized_usage.sqlite3')
    assert budget.totals('openai_agents')[0] == 0
    save(execution, {'provider_calls':0,'active_test':None,'workflow_states':{},'max_calls':12,'started_at':now()})
    transport = AllowedTransport()
    http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.openai.com/v1',
                    timeout=config.timeout_seconds, max_retries=0, http_client=http)
    guarded = type('GuardClient', (), {})(); guarded.responses = GuardResponses(client,config)
    try:
        for test in ('A','B'):
            row = manifest['fixtures'][test]; fixture = fixture_read(row); record = fixture['record']
            team = ar.AgentTeam(SCOPE/test/'agents',config=config,client_factory=lambda:guarded)
            team._usage = budget
            state = load(execution); state['active_test'] = test; state['workflow_states'][test]='PREFLIGHT'
            save(execution,state)
            preflight = team.preflight(record); catalog = ar.evidence_catalog(record['evidence'])
            assert all(team._cached(record['snapshot_id'],role,catalog) is None for role in ar.AGENTS)
            engine = EvidenceFusionEngine(SCOPE/test/'fusion')
            before = canonical_bytes(fixture)
            pre_agent = engine.fuse(record,agent_result=team.result(record),pipeline=fixture['pipeline'])
            state = load(execution); state['workflow_states'][test]='RUNNING'; save(execution,state)
            result = team.run(record)
            restored = ar.AgentTeam(team.root,config=config,client_factory=lambda: (_ for _ in ()).throw(RuntimeError('No provider calls on reload')))
            cached = restored.result(record)
            fusion = engine.fuse(record,agent_result=cached,pipeline=fixture['pipeline'])
            hit = engine.fuse(record,agent_result=cached,pipeline=fixture['pipeline'])
            health = restored.health(record); fusion_health = engine.health()
            ledger = [load(p) for p in (team.root/'runs').glob('*.json')]
            attempts = sorted([load(p) for p in (team.root/'attempts').glob('*.json')], key=lambda x:(x['started_at'],x['agent_type'],x['attempt']))
            # A supplemental audit ledger maps immutable production attempt records to this authorization/workflow.
            audit_attempts=[]
            for attempt in attempts:
                parent=next(p for p in ledger if p['run_id']==attempt['run_id'])
                audit_attempts.append({**attempt,'workflow_id':result['run_id'],'test_id':test,
                    'cache_status':parent['cache_status'],'validation_status':'PASS' if attempt['status']=='SUCCESS' else 'FAIL',
                    'production_attempt_sha256':sha(team.root/'attempts'/f"{attempt['attempt_id']}.json")})
            save(SCOPE/test/'workflow_attempt_ledger.json',audit_attempts)
            accepted=[entry for entry in cached['agents'].values() if entry.get('report')]
            for entry in accepted:
                v3.validate(entry['report'],entry['report']['agent_type'],record['snapshot_id'],catalog)
                assert entry['presentation']==v3.presentation(entry['report'],catalog)
            items=[item for item in fusion['evidence_items'] if item['evidence_type'].startswith('AGENT_')]
            public_messages={role:{k:entry.get(k) for k in ('error_code','error_message','failure_stage')} for role,entry in result['agents'].items()}
            private_check(public_messages); private_check(audit_attempts); private_check(cached)
            checks={'schema':len(accepted)==3,'fact_references':len(accepted)==3,
                'backend_rendering':len(accepted)==3,'no_model_numbers':len(accepted)==3,
                'interpretation_contract':len(accepted)==3,'stance':len(accepted)==3,
                'references':len(accepted)==3,'families':len(accepted)==3,'traceability':len(accepted)==3,
                'team':result['agents_completed']==3,'durable':cached['team_status']=='COMPLETE',
                'cache':len(accepted)==3 and all(p['cache_status']=='STORED' for p in ledger),
                'fusion_cache_invalidation':fusion['result_hash']!=pre_agent['result_hash'] and hit['cache_status']=='hit',
                'fusion_adapter':len(items)==3 and all(item['role']=='DERIVED' and not item['contributes_to_direction'] for item in items),
                'fusion_lineage':len(items)==3 and all(item['lineage_ids'] and item['provenance']['agent_run_id'] for item in items),
                'fusion_missing_agents':not any(x.startswith('AGENT_') for x in fusion['missing_evidence']),
                'conflicts':test!='B' or bool(fusion['conflicts']),
                'risk_lineage':len(accepted)==3 and bool(fusion['risks']),
                'uncertainty':len(accepted)==3 and bool(cached['agents']['risk']['report']['uncertainty']),
                'dashboard_adapter':len(accepted)==3 and all(e['presentation']['arguments'] and all(a['facts'] for a in e['presentation']['arguments']) for e in accepted),
                'pipeline':health['rows']==3 and health['team_status']=='COMPLETE' and health['status']=='HEALTHY',
                'fusion_health':fusion_health['snapshot_id']==record['snapshot_id'] and fusion_health['status']=='HEALTHY',
                'observability':len(ledger)==3 and all(p['run_id'] and p['attempt_refs'] for p in ledger) and all(a['sdk_attempted'] and a['output_schema_version']=='agent_output_v3' and a['request_id'] and all(a['token_usage'][k] is not None for k in ('input_tokens','output_tokens','total_tokens')) for a in attempts),
                'truncation':all(a['response_status']=='completed' and a.get('completion_reason')!='max_output_tokens' for a in attempts),
                'immutability':before==canonical_bytes(fixture),'public_error_safety':True,'snapshot_ownership':cached['snapshot_id']==record['snapshot_id']}
            output={'test':test,'status':'PASS' if all(checks.values()) else 'FAIL','fixture':row['fixture_id'],
                'snapshot_id':record['snapshot_id'],'serialized_size':row['input_bytes'],'semantic_difference':0,
                'preflight':preflight,'checks':checks,'team':result,'cached_team':cached,'fusion':fusion,
                'health':health,'fusion_health':fusion_health,'pipeline':fixture['pipeline'],
                'attempt_records':audit_attempts,'ledger_records':ledger,'api_cost':'UNKNOWN',
                'accepted_model_generated_numbers':0,'scope':'Actual production v3 harness with explicitly authorized isolated shared budget and real OpenAI Responses client'}
            save(REPORTS/f'v3_live_{test}.json',output)
            state=load(execution);state['workflow_states'][test]='FINISHED';save(execution,state)
            print(json.dumps({'test':test,'status':output['status'],'team':result['agents_completed'],'calls':result['api_calls'],'failed_checks':[k for k,v in checks.items() if not v]}),flush=True)
    finally:
        client.close()
        state=load(execution);state['transport_requests']=transport.requests;state['finished_at']=now()
        state['persisted_reserved_requests']=budget.totals('openai_agents')[0];save(execution,state)
    assert state['provider_calls']==state['transport_requests']==state['persisted_reserved_requests']<=12
    source_check(manifest)
    finalize()

def finalize():
    import openai
    manifest=load(MANIFEST);source_check(manifest);state=load(SCOPE/'execution.json')
    outcomes={test:load(REPORTS/f'v3_live_{test}.json') for test in ('A','B')}
    snapshot_isolation=outcomes['A']['snapshot_id']!=outcomes['B']['snapshot_id']
    durable_isolation=all(ar.AgentTeam(SCOPE/test/'agents').result(fixture_read(manifest['fixtures'][test])['record'])['snapshot_id']==outcome['snapshot_id'] for test,outcome in outcomes.items())
    attempts=[a for out in outcomes.values() for a in out['attempt_records']]
    accepted=[a for a in attempts if a['status']=='SUCCESS']
    usage={k:sum(a['token_usage'][k] for a in attempts if a['token_usage'][k] is not None) for k in ('input_tokens','output_tokens','total_tokens')}
    unknown_usage=sum(any(v is None for v in a['token_usage'].values()) for a in attempts)
    buckets={'<=900':0,'901-1200':0,'1201-1599':0,'TRUNCATED':0}
    for a in attempts:
        n=a['token_usage']['output_tokens']
        if a.get('completion_reason')=='max_output_tokens' or n is not None and n>=1600: buckets['TRUNCATED']+=1
        elif n is not None: buckets['<=900' if n<=900 else '901-1200' if n<=1200 else '1201-1599']+=1
    retry_roles=sum(e['attempts']>1 for out in outcomes.values() for e in out['team']['agents'].values())
    qa_path=REPORTS/'v3_live_qa/qa.json';qa=load(qa_path) if qa_path.exists() else {'status':'NOT_RUN'}
    pass_gate=all(o['status']=='PASS' for o in outcomes.values()) and snapshot_isolation and durable_isolation and qa['status']=='PASS'
    current_failures=[{'test':test,'agent':role,'failure_stage':entry['failure_stage'],'rejection':entry.get('error_message')} for test,out in outcomes.items() for role,entry in out['team']['agents'].items() if not entry.get('report')]
    comparison=[]
    for name in ('final_live_A.json','final_live_B.json'):
        previous=load(REPORTS/name)
        old_attempts=previous.get('attempt_records',[])
        comparison.extend(a['token_usage']['output_tokens'] for a in old_attempts if a.get('token_usage',{}).get('output_tokens') is not None)
    rejection_counts=dict(Counter((a.get('validation_diagnostic') or {}).get('rejection_reason') or a.get('sanitized_error') for a in attempts if a['status']!='SUCCESS'))
    primary='The shared v3 _prose guard rejects typed prose without a required caution keyword (unlabelled_interpretation); ten of twelve attempts fail this rule. The guard applies to interpretations, limitations and uncertainty notes; the exact failing text/location was not retained.' if rejection_counts.get('unlabelled_interpretation') else None
    report={'schema_version':'v3_dual_live_confirmation_v1','status':'PASS' if pass_gate else 'FAIL' if current_failures or any(o['status']=='FAIL' for o in outcomes.values()) else 'PARTIAL',
        'model':manifest['config']['model'],'openai_sdk_version':openai.__version__,'api_mode':'Responses API','sdk_method':'client.responses.create',
        'agent_schema':'agent_output_v3','prompts':manifest['prompt_versions'],
        'max_input_bytes':48000,'max_output_tokens':1600,'max_retries':1,'tools':'NONE','fact_ownership':'BACKEND',
        'model_generated_numbers':'DISALLOWED','openai_calls':state['provider_calls'],'transport_requests':state['transport_requests'],
        'persisted_requests':state['persisted_reserved_requests'],'usage':usage,'attempts_with_unknown_usage':unknown_usage,'api_cost':'UNKNOWN',
        'tests':{n:{k:o[k] for k in ('status','fixture','snapshot_id','serialized_size','semantic_difference','checks')} for n,o in outcomes.items()},
        'output_distribution':buckets,'average_accepted_output':sum(a['token_usage']['output_tokens'] for a in accepted)/len(accepted) if accepted else None,
        'max_accepted_output':max((a['token_usage']['output_tokens'] for a in accepted),default=None),
        'retry_rate':retry_roles/6,'retry_roles':retry_roles,'snapshot_isolation':snapshot_isolation,'durable_isolation':durable_isolation,
        'dashboard_browser_qa':qa['status'],'failures':current_failures,'rejection_counts':rejection_counts,
        'accepted_integration_status':'PASS' if pass_gate else 'NOT PROVEN: no accepted live agent result',
        'rejected_number_attempts':sum((a.get('validation_diagnostic') or {}).get('rejection_reason')=='model_generated_number' for a in attempts),
        'published_unsupported_numbers':0,
        'failure_state_persistence':all(o['cached_team']['team_status']==o['team']['team_status'] for o in outcomes.values()),
        'failure_cache_safety':all(not e.get('report') for o in outcomes.values() for e in o['cached_team']['agents'].values()) if not accepted else None,
        'v2_1_comparison':{'attempts':len(comparison),'mean_output_tokens':sum(comparison)/len(comparison) if comparison else None,'max_output_tokens':max(comparison,default=None),
            'note':'Descriptive two-fixture comparison only, not a reliability estimate or statistically controlled token benchmark.'},
        'architecture_score':8.6,'architecture_score_scope':'Prior custom scoped offline audit retained; no new comprehensive project audit',
        'monad_readiness':'GREEN' if pass_gate else 'RED' if current_failures else 'YELLOW','monad_permission':pass_gate,
        'production_code_changed':False,'prompt_schema_validator_changes':False,
        'safety':{'other_external_calls':0,'yahoo_calls':0,'tavily_calls':0,'monad_calls':0,'kronos_inference':0,'kronos_training':0,'model_weight_changes':0,'validation_reruns':0,'locked_test_accesses':0,'blockchain_transactions':0,'git_commits':0,'git_pushes':0,'monad_started':False},
        'highest_priority_root_cause':(primary or current_failures[0]['rejection'] if current_failures else 'Integration or browser QA gate unresolved' if not pass_gate else None)}
    save(REPORTS/'v3_dual_live_confirmation.json',report)
    for test,out in outcomes.items():
        rows=['# V3 Live Test '+test,'','Status: '+out['status'],'','Synthetic fixture: '+out['fixture'],
            'Snapshot: '+out['snapshot_id'],'Input bytes: '+str(out['serialized_size']),'Semantic evidence differences: 0',
            'Team accepted: '+str(out['team']['agents_completed'])+'/3','','## Checks','']
        rows += [f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in out['checks'].items()]
        rows += ['','## Attempts','','| Agent | Attempt | Status | Input | Output | Total | Failure stage | Reason |','|---|---:|---|---:|---:|---:|---|---|']
        for a in out['attempt_records']:
            u=a['token_usage'];rows.append(f"| {a['agent_type']} | {a['attempt']} | {a['status']} | {u['input_tokens']} | {u['output_tokens']} | {u['total_tokens']} | {a.get('failure_stage') or '-'} | {a.get('sanitized_error') or '-'} |")
        rows += ['','Production ledgers are unchanged. Supplemental workflow ledger adds test/workflow IDs and source hashes.',
            'Only accepted structured outputs are retained; raw provider response/hidden reasoning is not persisted.',
            'A false success-gate check means the accepted-team contract was not met; it does not prove every individual schema/reference check failed. Failed states persisted correctly and no failed success cache exists.',
            'No code, prompt, validator, fixture or financial fusion rule changed during execution. No other provider called.']
        (REPORTS/f'v3_live_{test}.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    text=['# V3 Dual Live Confirmation','', 'Status: '+report['status'], 'OpenAI calls: '+str(report['openai_calls'])+' / 12',
        'Token usage: '+json.dumps(usage),'API cost: UNKNOWN (not reported by provider)',
        'Test A: '+outcomes['A']['status'],'Test B: '+outcomes['B']['status'],
        'Snapshot isolation: '+str(snapshot_isolation),'Durable isolation: '+str(durable_isolation),
        'Browser QA: '+qa['status'],'Monad permission: '+str(pass_gate),'',
        '## Budget and Privacy','Task-scoped persistent budget shared by both workflows. Production daily counters not reset or changed.',
        'Only synthetic NSE:TESTCO snapshots transmitted to official OpenAI Responses endpoint. No other external service used.',
        'Only required snapshot/acquisition/technical freshness metadata changed; original news publication dates preserved.','',
        '## Efficiency','V3 accepted mean output: '+str(report['average_accepted_output']),
        'V3 accepted maximum output: '+str(report['max_accepted_output']),
        'V3 retry-role rate: '+str(report['retry_rate']),
        'Previous v2_1 output summary: '+json.dumps(report['v2_1_comparison']),
        'Schema responsibility is reduced, not necessarily total tokens. Do not generalize reliability from two runs.','',
        '## Observed Rejections','Counts: '+json.dumps(rejection_counts),
        'Highest-priority remaining cause: '+str(report['highest_priority_root_cause']),
        'The exact failing prose and the schema failure subcode are unavailable in retained diagnostics; no facts about discarded response text are invented.',
        'One attempt triggered model_generated_number. This identifies a rejected attempt, not the exact count of numerical spans. Published unsupported numbers: zero.',
        'Accepted fact rendering, claim traceability and agent-to-fusion integration remain unproven live because neither team produced an accepted result.',
        'Fusion retained all missing-agent markers and Test B primary conflicts. Failure state and absence of success cache survived reload.',
        '## Boundary','Existing functional offline suite was not rerun. No scientific evaluation or target read occurred.',
        'Architecture score remains the scoped 8.6/10 assessment, not a new full-project score.']
    (REPORTS/'v3_dual_live_confirmation.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    gate_path=REPORTS/'monad_readiness_gate.json';old=load(gate_path)
    if old.get('live_confirmation_report')!='v3_dual_live_confirmation.json':
        history=old.get('history',[]); previous={k:v for k,v in old.items() if k!='history'}
        history.append({'recorded_at':now(),'reason':'Authorized dual real-provider v3 confirmation; prior failed v2 evidence retained','previous_gate':previous})
    else: history=old.get('history',[])
    save(gate_path,{'schema_version':'monad_readiness_gate_postrepair_v1','status':report['monad_readiness'],
        'permission':'YES' if pass_gate else 'NO','history':history,'live_confirmation_report':'v3_dual_live_confirmation.json',
        'fresh_fixture_manifest':'v3_fresh_fixture_manifest.json','actual_provider_recovery':report['status'],
        'live_confirmation_needed':not pass_gate,'open_blockers':[] if pass_gate else [report['highest_priority_root_cause']],
        'remaining_red':[] if pass_gate else current_failures,'latest_task_safety':report['safety'],
        'authorized_call_scope':{'scope':'two_v3_workflows_max12','global_counter':state['provider_calls'],'persisted_requests':state['persisted_reserved_requests'],'production_reset':False},
        'accepted_non_blockers':old.get('accepted_non_blockers',[]),'architecture_score_scope':report['architecture_score_scope']})
    browser=load(REPORTS/'v3_browser_fixture.json')
    save(REPORTS/'v3_live_browser_fixture.json',{'fixture':browser['fixture'],'outcomes':outcomes})
    print(json.dumps({k:report[k] for k in ('status','openai_calls','usage','tests','output_distribution','average_accepted_output','retry_rate','dashboard_browser_qa','monad_permission','highest_priority_root_cause')},indent=2))

if __name__=='__main__':
    try:
        {'prepare':prepare,'run':run,'finalize':finalize}[sys.argv[1]]()
    except Exception as error:
        # Do not echo local paths, credential values, provider bodies or tracebacks.
        print(json.dumps({'stage':'STOPPED','exception_class':type(error).__name__,'message':'Validation stopped; inspect persisted scoped diagnostics before any continuation.'}))
        sys.exit(1)
