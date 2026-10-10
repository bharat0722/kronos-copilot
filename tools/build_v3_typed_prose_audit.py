"""Offline-only typed-prose replay, fresh synthetic freeze, and scoped audit artifacts."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import socket
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import agent_research as ar, agent_output_v3 as v3
from app.evidence_snapshot import canonical_bytes, snapshot_id
from research.tests.test_v3_typed_prose import typed_report, typed_team, OLD_HEDGE

REPORTS = ROOT / 'research/results/healthcheck_postrepair'

def read(name):
    return json.loads((REPORTS/name).read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, value):
    path = REPORTS/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))

def replay(fixtures):
    cases = []
    for test in ('A','B'):
        record = fixtures[test]['record']; catalog = ar.evidence_catalog(record['evidence'])
        for attempt in read(f'v3_live_{test}.json')['attempt_records']:
            role = attempt['agent_type']; report = typed_report(role, record)
            retained = attempt.get('validation_diagnostic') or {}
            historical_code = retained.get('rejection_reason') or 'schema_failure_details_not_retained'
            equivalent = copy.deepcopy(report)
            if historical_code == 'unlabelled_interpretation':
                equivalent['arguments'][0]['interpretation']['text'] = 'Technical momentum remains constructive.'
                old_reject = OLD_HEDGE.search(equivalent['arguments'][0]['interpretation']['text']) is None
                v3.validate(equivalent,role,record['snapshot_id'],catalog)
                result = 'PASS_TYPED_PROSE'
            else:
                if historical_code == 'model_generated_number':
                    equivalent['arguments'][0]['interpretation']['text'] = 'RSI is 63.2.'
                else:
                    equivalent['arguments'][0]['interpretation']['claim_type'] = 'FACT'
                old_reject = True
                try:
                    v3.validate(equivalent,role,record['snapshot_id'],catalog)
                    raise AssertionError('Unsafe structural equivalent accepted')
                except v3.ContractError as error:
                    result = error.code
            cases.append({'test':test,'attempt_id':attempt['attempt_id'],'run_id':attempt['run_id'],
                'agent':role,'attempt':attempt['attempt'],'historical_code':historical_code,
                'historical_field_and_exact_text':'NOT_RETAINED', 'old_behavior_rejects':old_reject,
                'new_behavior':result,'scope':'Authored structural equivalent, not reconstruction of discarded provider prose.'})
    assert len(cases)==12
    assert sum(c['historical_code']=='unlabelled_interpretation' for c in cases)==10
    return {'status':'PASS','cases':cases,'category_counts':dict(Counter(c['historical_code'] for c in cases)),
        'limitation':'The discarded schema failure cannot be diagnosed retroactively. Its equivalent tests continued schema rejection only.',
        'exact_provider_responses_replayed':0,'structural_equivalents':12,'external_calls':0}

def build():
    stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    run = hashlib.sha256(stamp.encode()).hexdigest()[:16]
    historical_names = ['v3_live_A.json','v3_live_B.json','v3_dual_live_confirmation.json',
        'v3_fresh_fixture_manifest.json','v3_live_fixtures/A.json','v3_live_fixtures/B.json',
        'agent_output_v3_contract.json','agent_output_v3_design.md','v3_live_retest_manifest.json']
    historical = {name:sha(REPORTS/name) for name in historical_names}
    old_manifest = read('v3_fresh_fixture_manifest.json')
    protected = {name:expected for name,expected in old_manifest['source_hashes'].items()
                 if name not in {'app/agent_output_v3.py','app/agent_research.py'}}
    assert all(sha(ROOT/name)==expected for name,expected in protected.items())
    prompts = {role:hashlib.sha256(ar.instructions(role).encode()).hexdigest() for role in ar.AGENTS}
    for test in ('A','B'):
        assert all(prompts[row['agent_type']]==row['prompt_sha256'] for row in read(f'v3_live_{test}.json')['ledger_records'])
    assert ar.PROMPT_VERSIONS==old_manifest['prompt_versions']
    assert asdict(ar.AgentConfig())==old_manifest['config']
    fixtures = {}; outcomes = {}; frozen = {}
    with patch.object(socket.socket,'connect',side_effect=AssertionError('External connection prohibited')), \
         patch.object(socket,'getaddrinfo',side_effect=AssertionError('External DNS prohibited')), \
         patch.dict(os.environ, {'OPENAI_API_KEY':'offline-typed-prose-only'}):
        for test in ('A','B'):
            old = read(f'v3_live_fixtures/{test}.json'); fixture = copy.deepcopy(old)
            assert sha(REPORTS/f'v3_live_fixtures/{test}.json')==old_manifest['fixtures'][test]['fixture_file_sha256']
            edits=[]
            for keys in [('record','created_at'),('record','evidence','market_data','retrieved_at'),('record','evidence','technicals','as_of')]:
                item=fixture
                for key in keys[:-1]:item=item[key]
                edits.append({'path':list(keys),'before':item[keys[-1]],'after':stamp})
                item[keys[-1]]=stamp
            fixture['record']['snapshot_id']=snapshot_id(fixture['record']['evidence'])
            restored=copy.deepcopy(fixture)
            for edit in edits:
                item=restored
                for key in edit['path'][:-1]:item=item[key]
                item[edit['path'][-1]]=edit['before']
            restored['record']['snapshot_id']=old['record']['snapshot_id']
            assert canonical_bytes(restored)==canonical_bytes(old)
            assert v3.fact_catalog(ar.evidence_catalog(fixture['record']['evidence']))==v3.fact_catalog(ar.evidence_catalog(old['record']['evidence']))
            fixtures[test]=fixture
            path=f'v3_next_live_fixtures/{test}.json'; save(path,fixture)
            outcome=typed_team(fixture,ROOT/'outputs/agent_research/v3_typed_prose_offline'/run/test)
            assert all(outcome['checks'].values()),outcome['checks']
            assert outcome['preflight']['status']=='PASS'
            outcomes[test]=outcome;save(f'v3_typed_prose_offline_{test}.json',outcome)
            wire=ar.serialize_agent_input(fixture['record'])
            assert len(wire)==old_manifest['fixtures'][test]['input_bytes']<48000
            frozen[test]={'fixture_id':fixture['fixture_id'],'fixture_path':f'research/results/healthcheck_postrepair/{path}',
                'fixture_file_sha256':sha(REPORTS/path),'snapshot_id':fixture['record']['snapshot_id'],
                'input_bytes':len(wire),'input_sha256':hashlib.sha256(wire).hexdigest(),
                'headroom_bytes':48000-len(wire),'preflight':outcome['preflight'],'offline_checks':outcome['checks'],
                'previous_snapshot_id':old['record']['snapshot_id'],'permitted_changes':edits,
                'fact_reference_changes':0,'semantic_content_changes':0,
                'future_live_cache_scope':f'outputs/agent_research/v3_typed_prose_live/{run}/{test}',
                'initial_live_cache_miss_required':True,'mock_cache_must_not_be_used':True}
        history_replay=replay(fixtures)
    assert frozen['A']['snapshot_id']!=frozen['B']['snapshot_id']
    sample=ar.evidence_catalog(fixtures['A']['record']['evidence'])
    assert read('agent_output_v3_contract.json')['strict_schema_examples']=={role:v3.schema(role,ar.allowed_evidence_ids(sample)) for role in ar.AGENTS}
    save('v3_typed_prose_replay.json',history_replay)
    save('v3_prose_validation_contract.json',{'schema_version':v3.SCHEMA_VERSION,
        'prose_validator_version':v3.PROSE_VALIDATOR_VERSION,'validator_version':v3.VALIDATOR_VERSION,
        'interpretation_type':'INTERPRETATION','support_type':'INTERPRETIVE','hedge_keyword_required':False,
        'typed_notes':['limitations','uncertainty'],'fact_ownership':'BACKEND','model_generated_numbers':False,
        'requirements':['Strict closed schema and bounds','Nonempty text','Known nonempty evidence IDs',
            'Compatible evidence families and role stance','Exact backend fact reference bindings',
            'No numbers, currencies, deterministic factual assertions, instructions or advice in model prose'],
        'cross_family_synthesis':'Allowed with complete citations; no fabricated family declaration',
        'legacy':'Historical v2/v2_1 heuristic and result semantics unchanged',
        'cache_identity':'snapshot + agent + model + prompt SHA/version + schema + validator version',
        'limitations':['Not universal semantic entailment','Qualitative support is not calibrated probability']})
    save('v3_rejection_diagnostic_contract.json',{'version':v3.DIAGNOSTIC_VERSION,'schema':v3.SCHEMA_VERSION,
        'required':['run_id','agent_type','attempt','schema_version','prompt_version','validator_version','prose_validator_version',
            'rule_code','json_path','argument_id','field_type','claim_type','evidence_ids','evidence_families','text_excerpt','reason'],
        'nullable':['argument_id','field_type','claim_type','text_excerpt'],
        'text_excerpt_limit':240,'raw_root_or_invalid_json_excerpt':None,
        'redaction':['Secret environment values','API key and Bearer patterns','Windows/UNC/Unix filesystem paths','Private keys','Emails and URLs'],
        'forbidden':['Hidden reasoning','Complete response','Authorization headers','Environment dumps','Secrets'],
        'storage':'Sanitized durable attempt record; parent ledger references attempts; not public response',
        'failure_types':['Schema','Parse','Numerical','Claim'],'invalid_json_location':'$ plus parser line/column, no raw payload',
        'legacy_diagnostics':'Unchanged'})
    sources=list(old_manifest['source_hashes'])+['research/tests/test_v3_typed_prose.py','research/tests/test_agent_output_v3.py',
        'tools/run_offline_health_tests.py','tools/build_v3_typed_prose_audit.py']
    save('v3_next_live_manifest.json',{'schema_version':'v3_typed_prose_live_manifest_v1','frozen_at':stamp,
        'expires_at':(datetime.fromisoformat(stamp)+timedelta(hours=1)).isoformat(),
        'agent_schema':v3.SCHEMA_VERSION,'validator':v3.VALIDATOR_VERSION,'prose_validator':v3.PROSE_VALIDATOR_VERSION,
        'renderer':v3.RENDERER_VERSION,'prompt_versions':ar.PROMPT_VERSIONS,'prompt_sha256':prompts,
        'config':asdict(ar.AgentConfig()),'max_input_bytes':48000,'max_output_tokens':1600,
        'loop_limit':1,'retry_limit':1,'tools':'NONE','daily_call_limit':12,'max_workflows':2,'max_live_calls':12,
        'live_authorized':False,'live_executed':False,'synthetic_only':True,'fixtures':frozen,
        'execution_conditions':['Fresh explicit authorization required','All source/fixture/wire hashes must match',
            'Exact production preflight and one-hour snapshot/acquisition freshness guard must pass',
            'If expired, separately authorize timestamp-only refreeze; no silent fixture edits',
            'Use separate empty live cache scopes; never offline mock caches',
            'Do not reset/bypass persisted daily production budget','No contract edits or additional diagnostic calls during live validation'],
        'publication_dates_and_financial_content':'Unchanged','source_hashes':{name:sha(ROOT/name) for name in sources},
        'monad_permission':False})
    base=read('v3_browser_fixture.json')
    save('v3_typed_prose_browser_fixture.json',{'fixture':base['fixture'],'outcomes':outcomes})
    tests=read('v3_typed_prose_tests.json')
    assert tests['failed']==tests['errors']==tests['blocked_external_attempts']==0
    assert tests['passed']>=299
    qa_path=REPORTS/'v3_typed_prose_qa/qa.json'
    qa=json.loads(qa_path.read_text()) if qa_path.exists() else {'status':'PENDING'}
    status='PASS' if qa['status']=='PASS' else 'PARTIAL'
    assert all(sha(REPORTS/name)==expected for name,expected in historical.items())
    report={'status':status,'root_cause':'V3 _prose reused a caution-word gate after the closed schema already typed INTERPRETATION; it also gated typed limitations/uncertainty.',
        'schema':v3.SCHEMA_VERSION,'validator':v3.VALIDATOR_VERSION,'prose_validator':v3.PROSE_VALIDATOR_VERSION,
        'prompt_versions':ar.PROMPT_VERSIONS,'prompts_changed':False,'schema_changed':False,
        'typed_without_hedge':'PASS','fact_ownership':'BACKEND','model_generated_numbers':'DISALLOWED',
        'legacy_isolation':'PASS','diagnostic_location':'PASS','diagnostic_excerpt':'PASS','diagnostic_rule':'PASS',
        'tests':tests,'teams':{test:outcome['checks'] for test,outcome in outcomes.items()},
        'historical_replay':history_replay,'browser_qa':qa,'gstack':'PARTIAL',
        'gstack_scope':'Installed review/checklist and CSO LLM-security checklist applied locally. Windows native browse QA available; Bash preamble/Aside unavailable. No network setup or outside-model calls.',
        'gstack_runtime_evidence':{'bash':'NOT_FOUND','aside':'NOT_AVAILABLE','browse_dist_binary':'Windows browse.exe verified healthy'},
        'architecture_score':8.7,'architecture_scope':'Scoped responsibility-boundary assessment, not a gstack composite or full project audit',
        'architecture_findings':['One shared v3 validator','Schema typing authoritative; no magic keyword correctness gate',
            'Backend fact ownership retained','Closed schema and reference/stance checks retained','Legacy validator unchanged',
            'Versioned agent/fusion acceptance caches','Precise bounded diagnostics stay inside durable server-side attempts'],
        'review_residuals':['Deterministic prose guards do not establish universal semantic truth',
            'Unchanged prompts still suggest cautious wording; it is permitted guidance, no longer a validation prerequisite',
            'Live provider acceptance remains unverified after this offline repair'],
        'next_manifest':'research/results/healthcheck_postrepair/v3_next_live_manifest.json',
        'frozen_inputs':{test:{key:value for key,value in item.items() if key in ('fixture_id','snapshot_id','input_bytes','input_sha256','headroom_bytes')} for test,item in frozen.items()},
        'protected_sources_unchanged':True,'historical_artifact_hashes':historical,
        'offline_roles':'GREEN OFFLINE','team_health':'YELLOW PENDING LIVE','monad_permission':False,
        'live_retest_ready':status=='PASS','remaining_offline_blockers':[] if status=='PASS' else ['Browser QA pending'],
        'safety':{'openai_calls':0,'other_external_calls':0,'kronos_inference':0,'training':0,'validation_reruns':0,
            'locked_test_access':0,'monad_code_started':False,'commit':False,'push':False},
        'verification_history':['Initial run found duplicate mock argument prose and diagnostic test edge cases; corrected without weakening guards.',
            'Final full offline suite and both mock teams verified after corrections.'],
        'next_action':'Authorize another fresh normal + adversarial V3 live Agent Team confirmation.'}
    save('v3_typed_prose_repair.json',report)
    markdown=f"""# V3 Typed-Prose Repair and Diagnostic Hardening

## Verdict
{status} offline. Bull/Bear/Risk: GREEN OFFLINE. Team: YELLOW PENDING LIVE. Monad permission: NO.

## Root cause and call map
AgentTeam request -> Responses API output_text -> JSON parse -> validate_current_output -> v3.validate -> closed _shape -> typed notes/interpretations -> _prose -> fact references/stance -> durable attempt/run ledger -> cache/publish -> fusion/dashboard adapters.

The former v3 `_prose` required caution words even after the schema established INTERPRETATION / INTERPRETIVE. It also checked typed limitations and uncertainty. Ten retained attempts failed that rule, but their exact prose and field locations were discarded. This audit does not pretend to recover them. Historical v2/v2_1 validate_output and its interpretive-word heuristic are untouched.

## Narrow repair
V3 classification is structural. Keywords are optional, not evidence of truth. Schema remains `{v3.SCHEMA_VERSION}`. Prompts remain Bull v9 / Bear v8 / Risk v8, with prompt hashes verified against retained live ledgers. Renderer unchanged. Acceptance validator: `{v3.VALIDATOR_VERSION}`; prose validator: `{v3.PROSE_VALIDATOR_VERSION}`. Cache identity already includes the acceptance validator, including fusion's agent adapter identity. Old accepted/rejected results are not silently reinterpreted.

Facts, values, units and directions remain backend-owned. Number-free prose, exact fact bindings, known citations, compatible families, role stances, bounds, explicit-fact/advice/injection guards remain enforced. Legitimate cross-family interpretation cites all sources. Bounded deterministic guards are not universal semantic entailment; qualitative support is not probability.

## Diagnostics
Failures retain rule, trusted JSON path, argument/type, cited IDs/families, reason, version, run/attempt/prompt and a sanitized excerpt of at most 240 characters. Schema failures now retain diagnostics too. Invalid JSON retains parser line/column but not raw payload. Malformed root responses are not excerpted. Environment secrets, keys, Bearer strings, private keys and filesystem paths are redacted. No hidden reasoning or full provider response is stored. Public errors remain generic and unchanged.

## Verification
Full offline suite: {tests['passed']} passed / {tests['failed']+tests['errors']} failed / {tests['skipped']} skipped. Existing Yahoo live opt-in remains skipped. External connection/DNS blocking was active, with zero attempted external connections. Both native mocked production teams: 3/3 accepted, durable COMPLETE, validated caches/ledgers, input immutability, fusion lineage, no double counting, and adversarial conflicts retained.

Twelve structural replay cases: ten former keyword rejections become valid typed prose; one numerical and one representative schema violation remain rejected. Exact historical responses were not retained. All historical live reports/frozen fixtures and protected product/scientific modules remain byte-identical.

## Scoped gstack and architecture review
GSTACK: PARTIAL. Installed review/checklist (LLM trust, data safety, concurrency, enum consumers, exceptions, cache and test gaps) and CSO AI/security checklist applied to this change. Native Windows browse.exe was verified healthy. Bash preamble and Aside are unavailable; no setup download or outside-model call was made. Local Playwright browser QA is reported separately: {qa['status']}. This is not a claim that every full gstack workflow ran.

Custom scoped architecture assessment: 8.7/10. The responsibility boundary improves: typing determines classification, facts stay backend-owned, one shared validator serves all roles, legacy contracts are isolated and diagnostics are precise. Existing large harness ownership and universal semantic-entailment limits remain outside this repair.

## Fresh freeze and limits
Normal: {frozen['A']['input_bytes']} bytes; adversarial: {frozen['B']['input_bytes']} bytes. Maximum input 48000 bytes and output 1600 tokens unchanged. Loop 1 / retry 1 / tools NONE / daily cap 12 unchanged. Only three existing synthetic freshness timestamps were renewed; financial/news content and publication dates were not edited. Frozen fixture, wire, snapshot, prompt and source hashes are in v3_next_live_manifest.json. Future runs need fresh authorization, matching hashes, an unexpired one-hour freeze, empty live cache namespaces and sufficient persisted budget. Expiration requires an explicitly authorized timestamp-only refreeze, not silent edits.

## Safety and next action
OpenAI / Yahoo / Tavily / Monad / other external calls: 0. Inference/training/validation/locked-test access: 0. No commit, push or Monad work. Historical failed live evidence remains failed; offline success is not live confirmation.

Authorize another fresh normal + adversarial V3 live Agent Team confirmation. Do not execute without authorization.
"""
    (REPORTS/'v3_typed_prose_repair.md').write_text(markdown,encoding='utf-8')
    print(json.dumps({'status':status,'teams':report['teams'],'inputs':report['frozen_inputs'],'tests':tests,'qa':qa['status'],'external_calls':0}))

def finalize():
    # Attach completed QA without rerunning mocks, refreezing fixtures or changing their hashes.
    report=read('v3_typed_prose_repair.json'); manifest=read('v3_next_live_manifest.json')
    qa=read('v3_typed_prose_qa/qa.json')
    native=json.loads((REPORTS/'v3_typed_prose_qa/native_gstack_qa.json').read_text(encoding='utf-8-sig'))
    tests=read('v3_typed_prose_tests.json')
    assert qa['status']==native['status']=='PASS'
    assert not native['external_request_detected']
    assert tests['failed']==tests['errors']==tests['blocked_external_attempts']==0
    for name,expected in report['historical_artifact_hashes'].items():assert sha(REPORTS/name)==expected
    for source,expected in manifest['source_hashes'].items():
        if source!='tools/build_v3_typed_prose_audit.py':assert sha(ROOT/source)==expected
    for test,item in manifest['fixtures'].items():
        path=ROOT/item['fixture_path']; fixture=json.loads(path.read_text())
        wire=ar.serialize_agent_input(fixture['record'])
        assert sha(path)==item['fixture_file_sha256']
        assert hashlib.sha256(wire).hexdigest()==item['input_sha256']
        assert snapshot_id(fixture['record']['evidence'])==item['snapshot_id']
        assert len(wire)==item['input_bytes']
    for source in ('tools/build_v3_typed_prose_audit.py','tools/v3_dashboard_qa.cjs',
                   'tools/v3_typed_prose_mock_server.cjs','tools/v3_typed_prose_gstack_qa.ps1'):
        manifest['source_hashes'][source]=sha(ROOT/source)
    manifest['offline_verification']={'tests':tests,'playwright_cases':6,'native_gstack_cases':6,
        'native_browser_build':native['native_browser_build'],'no_external_calls':True}
    save('v3_next_live_manifest.json',manifest)
    report.update(status='PASS',tests=tests,browser_qa=qa,native_gstack_qa=native,
        live_retest_ready=True,remaining_offline_blockers=[])
    report['gstack_scope']='Installed review/security checklists applied to scoped code; native Windows gstack browser QA PASS (six cases), separate Playwright QA PASS (six cases). Bash preamble and Aside unavailable; no outside-model review or network setup.'
    report['gstack_runtime_evidence']={'bash':'NOT_FOUND','aside':'NOT_AVAILABLE','browse_dist_binary':'Windows browse.exe healthy, native QA executed',
        'native_browser_build':native['native_browser_build']}
    report['scoped_review']={'code':'PASS','security':'PASS','native_browser':'PASS','blockers':[],
        'checks':['LLM output remains closed-schema and validated before cache/publication',
            'No new tools, execution, SQL, shell or external fetch path','Existing route auth/origin/budget protections unchanged',
            'Diagnostic fields use bounded sanitized metadata; root payload and reasoning are not retained',
            'Version change flows through agent and fusion cache identities','Ledger-before-cache and failures without success-cache retained',
            'Full mocked failure and success paths pass; legacy behavior unchanged'],
        'scope':'Only changed validation/diagnostics and their consumers; not a whole-repository security audit'}
    save('v3_typed_prose_repair.json',report)
    path=REPORTS/'v3_typed_prose_repair.md'; text=path.read_text(encoding='utf-8')
    text=text.replace('PARTIAL offline.','PASS offline.').replace('Local Playwright browser QA is reported separately: PENDING.','Local Playwright browser QA: PASS (six cases). Native gstack browser QA: PASS (six cases), including desktop/phone/iPad and reload. Bash preamble and Aside remain unavailable.')
    text=text.replace('Native Bash preamble, Aside and compiled browse runtime are unavailable here;',
        'Native Windows browse.exe was discovered and executed successfully; Bash preamble and Aside are unavailable;')
    text+='\n## Final scoped review\nCode and security checklist checks: PASS, no scoped blockers. Native gstack browser and Playwright each passed six cases with no overflow, console errors, secret/path display or external app requests. Browser runtime stopped and local QA server stopped after verification. No full outside-model review or full-repository security certification is implied.\n'
    path.write_text(text,encoding='utf-8')
    print(json.dumps({'status':'PASS','tests':tests,'mock_teams':'A 3/3, B 3/3','native_qa':native['status'],
        'gstack':'PARTIAL','fixture_hashes_preserved':True,'protected_history_unchanged':True,'external_calls':0}))

if __name__=='__main__':
    finalize() if '--finalize' in sys.argv else build()
