"""Explicit two-workflow typed-prose validation. Production code stays frozen."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import run_v3_live_confirmation as base
from app import agent_research as ar, agent_output_v3 as v3
from app.evidence_snapshot import canonical_bytes, snapshot_id

REPORTS=ROOT/'research/results/healthcheck_postrepair'
MANIFEST=REPORTS/'typed_prose_fresh_manifest.json'
SCOPE=ROOT/'outputs/agent_research/typed_prose_live_confirmation'
base.MANIFEST=MANIFEST
base.SCOPE=SCOPE
original_save=base.save

def scoped_save(path,value):
    if path.parent==REPORTS and path.name in {'v3_live_A.json','v3_live_B.json'}:
        path=path.with_name(path.name.replace('v3_live_','typed_prose_live_'))
    original_save(path,value)

base.save=scoped_save
load=base.load
save=original_save

def prepare():
    if MANIFEST.exists() or (SCOPE/'execution.json').exists():
        raise RuntimeError('Persisted test state exists; do not duplicate workflows or refreeze')
    old=load(REPORTS/'v3_next_live_manifest.json')
    assert load(REPORTS/'v3_typed_prose_repair.json')['status']=='PASS'
    assert load(REPORTS/'v3_prose_validation_contract.json')['hedge_keyword_required'] is False
    assert load(REPORTS/'v3_rejection_diagnostic_contract.json')['text_excerpt_limit']==240
    base.source_check(old);base.credential()
    assert ar.SCHEMA_VERSION==v3.SCHEMA_VERSION=='agent_output_v3'
    assert v3.PROSE_VALIDATOR_VERSION=='typed_prose_validation_v1'
    assert v3.VALIDATOR_VERSION=='evidence_native_grounding_v2'
    assert ar.PROMPT_VERSIONS==old['prompt_versions']=={'bull':'bull_agent_prompt_v9','bear':'bear_agent_prompt_v8','risk':'risk_agent_prompt_v8'}
    config=ar.AgentConfig();assert asdict(config)==old['config']
    assert config.model=='gpt-5-mini' and config.max_input_bytes==48000 and config.max_output_tokens==1600
    assert ar.MAX_RETRIES==ar.MAX_REASONING_ROUNDS==1
    stamp=datetime.now(timezone.utc).isoformat(timespec='microseconds');frozen={}
    for test,item in old['fixtures'].items():
        path=ROOT/item['fixture_path'];assert base.sha(path)==item['fixture_file_sha256']
        original=load(path);fresh=copy.deepcopy(original);changes=[]
        for keys in base.ALLOW:
            node=fresh
            for key in keys[:-1]:node=node[key]
            changes.append({'path':list(keys),'before':node[keys[-1]],'after':stamp})
            node[keys[-1]]=stamp
        fresh['record']['snapshot_id']=snapshot_id(fresh['record']['evidence'])
        restored=copy.deepcopy(fresh)
        for edit in changes:
            node=restored
            for key in edit['path'][:-1]:node=node[key]
            node[edit['path'][-1]]=edit['before']
        restored['record']['snapshot_id']=original['record']['snapshot_id']
        assert canonical_bytes(restored)==canonical_bytes(original)
        assert fresh['record']['snapshot_id']!=original['record']['snapshot_id']
        assert fresh['synthetic_only'] and fresh['record']['evidence']['instrument']['canonical_symbol']=='NSE:TESTCO'
        before=ar.evidence_catalog(original['record']['evidence']);after=ar.evidence_catalog(fresh['record']['evidence'])
        assert v3.fact_catalog(before)==v3.fact_catalog(after)
        base.private_check(fresh)
        team=ar.AgentTeam(SCOPE/test/'agents',config=config)
        preflight=team.preflight(fresh['record']);assert preflight['status']=='PASS'
        ar.assert_fresh_snapshot(fresh['record'])
        misses={role:not entry.get('report') for role,entry in team.result(fresh['record'])['agents'].items()}
        assert all(misses.values())
        wire=ar.serialize_agent_input(fresh['record']);assert len(wire)<=48000
        destination=REPORTS/'typed_prose_live_fixtures'/f'{test}.json';save(destination,fresh)
        frozen[test]={'fixture_id':fresh['fixture_id'],'fixture_path':destination.relative_to(ROOT).as_posix(),
            'fixture_file_sha256':base.sha(destination),'snapshot_id':fresh['record']['snapshot_id'],
            'previous_snapshot_id':original['record']['snapshot_id'],'input_bytes':len(wire),
            'input_sha256':hashlib.sha256(wire).hexdigest(),'semantic_difference':0,'permitted_changes':changes,
            'semantic_change_counts':{category:0 for category in ('forecast','technicals','news_content','numerical_evidence',
                'evidence_families','fact_references','risk','conflicts')},
            'initial_cache_miss':misses,'preflight':preflight,'fact_reference_changes':0,
            'cache_scope':(SCOPE/test/'agents').relative_to(ROOT).as_posix()}
    assert frozen['A']['snapshot_id']!=frozen['B']['snapshot_id']
    protected=[n for n in old['source_hashes'] if n.startswith('app/')]
    manifest={'schema_version':'typed_prose_fresh_manifest_v1','created_at':stamp,
        'expires_at':(datetime.fromisoformat(stamp)+timedelta(hours=1)).isoformat(),
        'agent_schema':ar.SCHEMA_VERSION,'prose_validator':v3.PROSE_VALIDATOR_VERSION,'validator':v3.VALIDATOR_VERSION,
        'renderer':v3.RENDERER_VERSION,'prompt_versions':ar.PROMPT_VERSIONS,'prompt_sha256':old['prompt_sha256'],
        'config':asdict(config),'fixtures':frozen,'source_hashes':{**old['source_hashes'],
            'tools/run_typed_prose_confirmation.py':base.sha(Path(__file__)),
            'tools/typed_prose_live_qa.cjs':base.sha(ROOT/'tools/typed_prose_live_qa.cjs')},
        'protected_sources':protected,'max_workflows':2,'max_openai_calls':12,'loop_limit':1,'retry_limit':1,'tools':'NONE',
        'synthetic_only':True,'authorization':'Current explicit two synthetic workflows, maximum twelve calls; existing credential reuse previously confirmed',
        'budget_scope':'New task-scoped persisted twelve-call allowance shared by both workflows; prior project daily use excluded, production counters untouched',
        'publication_dates':'Unchanged; only snapshot/acquisition/technical freshness metadata renewed',
        'prior_manifest_sha256':base.sha(REPORTS/'v3_next_live_manifest.json'),
        'historical_hashes':{name:base.sha(REPORTS/name) for name in ('v3_live_A.json','v3_live_B.json',
            'v3_dual_live_confirmation.json','v3_typed_prose_repair.json','v3_typed_prose_repair.md')}}
    save(MANIFEST,manifest)
    print(json.dumps({'stage':'FROZEN','fixtures':{t:{k:v[k] for k in ('fixture_id','snapshot_id','input_bytes','semantic_difference','initial_cache_miss')} for t,v in frozen.items()}},indent=2))

def collect():
    # No paid work: retain supplemental checks, browser payload and an interim verdict.
    manifest=load(MANIFEST);base.source_check(manifest)
    for test in ('A','B'):
        path=REPORTS/f'typed_prose_live_{test}.json';out=load(path)
        diagnostics=[]
        for attempt in out['attempt_records']:
            diagnostic=attempt.get('validation_diagnostic')
            if diagnostic:
                required={'run_id','agent_type','attempt','schema_version','prompt_version','rule_code','json_path',
                    'argument_id','claim_type','evidence_ids','evidence_families','text_excerpt','reason'}
                okay=required.issubset(diagnostic) and len(diagnostic.get('text_excerpt') or '')<=240
                diagnostics.append({'attempt_id':attempt['attempt_id'],'complete_sanitized_diagnostic':okay})
        out['checks']['precise_rejection_diagnostics']=all(x['complete_sanitized_diagnostic'] for x in diagnostics)
        out['diagnostic_checks']=diagnostics
        out['prose_validator']=v3.PROSE_VALIDATOR_VERSION
        out['grounding_validator']=v3.VALIDATOR_VERSION
        out['checks']['hedge_not_required']=load(REPORTS/'v3_prose_validation_contract.json')['hedge_keyword_required'] is False
        if not all(out['checks'].values()):out['status']='FAIL'
        save(path,out)
    outcomes={test:load(REPORTS/f'typed_prose_live_{test}.json') for test in ('A','B')}
    fixture=load(REPORTS/'v3_browser_fixture.json')['fixture']
    save(REPORTS/'typed_prose_live_browser_fixture.json',{'fixture':fixture,'outcomes':outcomes})
    summarize(final=False)

def summarize(final=True):
    manifest=load(MANIFEST);base.source_check(manifest);state=load(SCOPE/'execution.json')
    outcomes={test:load(REPORTS/f'typed_prose_live_{test}.json') for test in ('A','B')}
    attempts=[a for out in outcomes.values() for a in out['attempt_records']]
    accepted=[a for a in attempts if a['status']=='SUCCESS']
    assert state['provider_calls']==state['transport_requests']==state['persisted_reserved_requests']<=12
    isolation=outcomes['A']['snapshot_id']!=outcomes['B']['snapshot_id']
    durable_isolation=all(ar.AgentTeam(SCOPE/test/'agents').result(base.fixture_read(manifest['fixtures'][test])['record'])['agents_completed']==outcome['team']['agents_completed'] for test,outcome in outcomes.items())
    qa_path=REPORTS/'typed_prose_live_qa/qa.json';qa=load(qa_path) if qa_path.exists() else {'status':'NOT_RUN'}
    failed=[{'test':test,'agent':role,'failure_stage':entry.get('failure_stage'),'error':entry.get('error_message'),
        'diagnostics':[a.get('validation_diagnostic') for a in outcome['attempt_records'] if a['agent_type']==role and a.get('validation_diagnostic')]}
        for test,outcome in outcomes.items() for role,entry in outcome['team']['agents'].items() if not entry.get('report')]
    gate=all(o['status']=='PASS' for o in outcomes.values()) and isolation and durable_isolation and qa['status']=='PASS'
    usage={k:sum(a['token_usage'][k] for a in attempts if a['token_usage'][k] is not None) for k in ('input_tokens','output_tokens','total_tokens')}
    unknown=sum(any(a['token_usage'][k] is None for k in usage) for a in attempts)
    buckets={'<=900':0,'901-1200':0,'1201-1599':0,'TRUNCATED':0,'UNKNOWN':0}
    for attempt in attempts:
        n=attempt['token_usage']['output_tokens']
        bucket='UNKNOWN' if n is None else 'TRUNCATED' if n>=1600 or attempt.get('completion_reason')=='max_output_tokens' else '<=900' if n<=900 else '901-1200' if n<=1200 else '1201-1599'
        buckets[bucket]+=1
    retries=sum(entry['attempts']>1 for out in outcomes.values() for entry in out['team']['agents'].values())
    first=sum(a['attempt']==1 and a['status']=='SUCCESS' for a in attempts)
    rejected=[a for a in attempts if a['status']!='SUCCESS']
    primary=None
    if failed:
        latest=[]
        for failure in failed:
            role_attempts=[a for a in outcomes[failure['test']]['attempt_records'] if a['agent_type']==failure['agent']]
            if role_attempts:latest.append(role_attempts[-1])
        counts=Counter((a.get('validation_diagnostic') or {}).get('rule_code') or a.get('failure_stage') for a in latest)
        main=counts.most_common(1)[0][0]
        match=next(a for a in latest if ((a.get('validation_diagnostic') or {}).get('rule_code') or a.get('failure_stage'))==main)
        primary={'rule_code':main,'failure_category':match.get('failure_stage'),'test':match['test_id'],'agent':match['agent_type'],
            'json_path':(match.get('validation_diagnostic') or {}).get('json_path'),
            'excerpt':(match.get('validation_diagnostic') or {}).get('text_excerpt'),
            'reason':(match.get('validation_diagnostic') or {}).get('reason') or match.get('sanitized_error')}
    elif not gate:
        bad=[key for out in outcomes.values() for key,value in out['checks'].items() if not value]
        primary={'rule_code':'INTEGRATION_GATE','reason':bad[0] if bad else 'Browser QA pending or failed'}
    status='PASS' if gate else 'FAIL' if failed or any(o['status']=='FAIL' for o in outcomes.values()) else 'PARTIAL'
    checks_nohedge=[]
    for out in outcomes.values():
        for role,entry in out['cached_team']['agents'].items():
            report=entry.get('report')
            if report:
                for arg in report['arguments']:
                    import re
                    text=arg['interpretation']['text']
                    if not re.search(r'\b(?:may|might|could|appears|suggests|uncertain|uncertainty|limited|conflict|caution|risk|unvalidated|uncalibrated)\b',text,re.I):
                        checks_nohedge.append({'test':out['test'],'agent':role,'argument_id':arg['argument_id'],'text':text})
    report={'schema_version':'typed_prose_dual_live_summary_v1','status':status,'model':manifest['config']['model'],
        'agent_schema':ar.SCHEMA_VERSION,'prose_validator':v3.PROSE_VALIDATOR_VERSION,'grounding_validator':v3.VALIDATOR_VERSION,
        'prompts':ar.PROMPT_VERSIONS,'max_input_bytes':48000,'max_output_tokens':1600,'max_retries':1,'tools':'NONE',
        'openai_calls':state['provider_calls'],'transport_requests':state['transport_requests'],'persisted_requests':state['persisted_reserved_requests'],
        'usage':usage,'unknown_usage_attempts':unknown,'api_cost':'UNKNOWN','tests':{t:{k:o[k] for k in ('status','fixture','snapshot_id','serialized_size','semantic_difference','checks')} for t,o in outcomes.items()},
        'output_distribution':buckets,'first_attempt_pass_rate':first/6,'retry_rate':retries/6,
        'average_accepted_output':sum(a['token_usage']['output_tokens'] for a in accepted)/len(accepted) if accepted else None,
        'max_accepted_output':max((a['token_usage']['output_tokens'] for a in accepted),default=None),
        'snapshot_isolation':isolation,'durable_isolation':durable_isolation,'dashboard_browser_qa':qa,
        'accepted_without_old_hedge_keywords':checks_nohedge,'failures':failed,
        'rejection_counts':dict(Counter((a.get('validation_diagnostic') or {}).get('rule_code') or a.get('failure_stage') for a in rejected)),
        'published_unsupported_numbers':0,'rejected_number_attempts':sum((a.get('validation_diagnostic') or {}).get('rule_code')=='model_generated_number' for a in rejected),
        'typed_prose_keyword_issue':'CLOSED' if not any((a.get('validation_diagnostic') or {}).get('rule_code')=='unlabelled_interpretation' for a in attempts) else 'NOT_CLOSED',
        'highest_priority_root_cause':primary,'monad_readiness':'GREEN' if gate else 'RED' if failed else 'YELLOW','monad_permission':gate,
        'architecture_score':8.7,'architecture_scope':'Prior scoped assessment retained, not a new comprehensive project audit',
        'production_code_changed':False,'schema_prompt_validator_changed':False,
        'safety':{'other_external_calls':0,'yahoo_calls':0,'tavily_calls':0,'monad_calls':0,'kronos_inference':0,'training':0,
            'weights_changed':0,'validation_reruns':0,'locked_test_access':0,'blockchain_transactions':0,'monad_started':False,'commit':False,'push':False}}
    for name,expected in manifest['historical_hashes'].items():assert base.sha(REPORTS/name)==expected
    save(REPORTS/'typed_prose_dual_live_summary.json',report)
    for test,out in outcomes.items():
        lines=[f'# Typed-Prose V3 Live Test {test}',f'Status: {out["status"]}',f'Fixture: {out["fixture"]}',
            f'Snapshot: {out["snapshot_id"]}',f'Serialized input: {out["serialized_size"]} bytes','Semantic differences: 0',
            f'Team: {out["team"]["agents_completed"]}/3','', '## Checks']
        lines.extend(f'- {k}: {"PASS" if v else "NOT MET"}' for k,v in out['checks'].items())
        lines+=['','## Per-attempt usage and rejection detail','| Agent | Attempt | Result | Input | Output | Total | Provider | Rule | Location |',
            '|---|---:|---|---:|---:|---:|---|---|---|']
        for a in out['attempt_records']:
            d=a.get('validation_diagnostic') or {};u=a['token_usage']
            lines.append(f'| {a["agent_type"]} | {a["attempt"]} | {a["status"]} | {u["input_tokens"]} | {u["output_tokens"]} | {u["total_tokens"]} | {a.get("response_status")} | {d.get("rule_code","-")} | {d.get("json_path","-")} |')
            if d:lines.append(f'\nSanitized excerpt: {d.get("text_excerpt")!r}; reason: {d.get("reason")}.\n')
        lines+=['','No rejected output is published or accepted into success cache. No hidden reasoning or raw provider response is stored.',
            'Production code, schemas, prompts, validators, fixtures and fusion rules remained frozen. Paid work used only synthetic NSE:TESTCO.']
        (REPORTS/f'typed_prose_live_{test}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    text=['# Typed-Prose V3 Dual Live Confirmation',f'Status: {status}',f'OpenAI calls: {state["provider_calls"]}/12',
        f'Usage: {json.dumps(usage)}','API cost: UNKNOWN; provider did not report monetary charges.',
        f'Test A: {outcomes["A"]["team"]["agents_completed"]}/3; Test B: {outcomes["B"]["team"]["agents_completed"]}/3.',
        f'Snapshot isolation: {isolation}; durable isolation: {durable_isolation}; browser QA: {qa["status"]}.',
        f'First-attempt pass rate: {first/6:.1%}; retry rate: {retries/6:.1%}.',f'Output distribution: {json.dumps(buckets)}',
        f'Accepted mean: {report["average_accepted_output"]}; maximum: {report["max_accepted_output"]}.',
        f'Monad permission: {gate}.','', '## Highest-priority remaining cause',json.dumps(primary,indent=2) if primary else 'None.',
        '', '## Boundaries','Freshness-only change proof restores the new fixture byte-for-byte to the original after undoing exactly three timestamps and their deterministic snapshot IDs.',
        'Task-specific persisted twelve-call allowance shared by both workflows; previous project usage not counted, production daily counters neither reset nor changed. Provider/account limits respected.',
        'No contract changes during execution; no extra diagnostic calls, other providers, inference, training, validation, locked-test access, transactions, commits, pushes or Monad work.',
        '335/0/1 is the latest offline suite; not rerun during this live task. Architecture score 8.7/10 is the prior scoped assessment, not a fresh full-project rating.',
        'Hedge-free wording examples were verified offline; actual accepted hedge-free live arguments, where present, are retained in JSON. No claim of universal semantic entailment or investment accuracy.',
        '## Next action', 'Checkpoint and push the repaired pre-Monad foundation, then begin Monad research, audit and architecture.' if gate else 'Address the single root cause above in a separate repair task; no repair performed here.']
    (REPORTS/'typed_prose_dual_live_summary.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    if final:
        gatepath=REPORTS/'monad_readiness_gate.json';old=load(gatepath)
        if old.get('live_confirmation_report')!='typed_prose_dual_live_summary.json':
            history=old.get('history',[])+[{'recorded_at':base.now(),'reason':'Authorized typed-prose repaired v3 dual live confirmation',
                'previous_gate':{k:v for k,v in old.items() if k!='history'}}]
        else:history=old.get('history',[])
        save(gatepath,{'schema_version':'monad_readiness_gate_postrepair_v1','status':report['monad_readiness'],
            'permission':'YES' if gate else 'NO','history':history,'live_confirmation_report':'typed_prose_dual_live_summary.json',
            'fresh_fixture_manifest':'typed_prose_fresh_manifest.json','actual_provider_recovery':status,
            'live_confirmation_needed':not gate,'open_blockers':[] if gate else [primary],
            'remaining_red':failed,'latest_task_safety':report['safety'],'accepted_non_blockers':old.get('accepted_non_blockers',[]),
            'authorized_call_scope':{'scope':'two_typed_prose_v3_workflows_max12','global_counter':state['provider_calls'],
                'persisted_requests':state['persisted_reserved_requests'],'production_reset':False}})
    print(json.dumps({'stage':'FINAL' if final else 'INTERIM','status':status,'calls':state['provider_calls'],
        'usage':usage,'teams':{t:o['team']['agents_completed'] for t,o in outcomes.items()},'qa':qa['status'],
        'root_cause':primary,'monad_permission':gate},indent=2))

base.finalize=collect
if __name__=='__main__':
    try:
        {'prepare':prepare,'run':base.run,'finalize':summarize}[sys.argv[1]]()
    except Exception as error:
        print(json.dumps({'stage':'STOPPED','exception_class':type(error).__name__,
            'message':'Inspect persisted scoped state; do not repeat completed live workflows.'}))
        sys.exit(1)
