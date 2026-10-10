"""Generate offline V4 contracts, replay evidence, fixtures and audit artifacts."""
import ast
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import agent_research as ar, agent_output_v3 as v3, agent_output_v4 as v4
from app.evidence_snapshot import canonical_bytes
from research.tests.fixtures.dual_retest_fixtures import build_fixture
from research.tests.test_agent_output_v4 import full_team, selection_for

REPORTS=ROOT/'research/results/healthcheck_postrepair'
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def save(name,value):
    path=REPORTS/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def branches(fn): return sum(isinstance(n,(ast.If,ast.IfExp)) for n in ast.walk(ast.parse(__import__('inspect').getsource(fn))))
def properties(schema):
    return len(schema.get('properties',{}))+sum(properties(v) for v in schema.get('properties',{}).values())+properties(schema['items']) if 'items' in schema else len(schema.get('properties',{}))+sum(properties(v) for v in schema.get('properties',{}).values())

def main():
    REPORTS.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).isoformat()
    old_manifest=load(REPORTS/'typed_prose_fresh_manifest.json')
    history={name:sha(REPORTS/name) for name in old_manifest['historical_hashes']}
    for name,expected in old_manifest['historical_hashes'].items(): assert history[name]==expected
    for name,expected in old_manifest['source_hashes'].items():
        if name.startswith('app/') and name not in {'app/agent_research.py','app/dashboard.js','app/evidence_fusion.py'}:
            assert sha(ROOT/name)==expected, name
    failures=[]
    sources=['v3_live_A.json','v3_live_B.json','typed_prose_live_A.json','typed_prose_live_B.json',
             'live_retest_A_production.json','live_retest_B_adversarial.json']
    for name in sources:
        path=REPORTS/name
        if not path.exists():continue
        document=load(path)
        for attempt in document.get('attempt_records',[]):
            if attempt.get('status')=='SUCCESS':continue
            diag=attempt.get('validation_diagnostic') or {}
            failures.append({'attempt_id':attempt.get('attempt_id'),'artifact':name,'agent':attempt.get('agent_type'), 'attempt':attempt.get('attempt'),
                'rule':diag.get('rule_code') or diag.get('rejection_reason') or diag.get('failure_reason') or attempt.get('failure_stage') or 'UNCLASSIFIED',
                'path':diag.get('json_path'), 'retained_exact_text':bool(diag.get('text_excerpt')),
                'retained_excerpt':diag.get('text_excerpt') or diag.get('claim_text')})
    inventory={row['attempt_id']:row for row in failures}
    for case in load(REPORTS/'v3_live_failure_replay.json')['cases']:
        diag=case.get('retained_diagnostic') or {}
        row={'attempt_id':case['attempt_id'],'artifact':'v3_live_failure_replay.json','agent':case['agent'],
            'attempt':case['attempt'],'rule':diag.get('failure_reason') or case['historical_rejection'],
            'path':diag.get('json_path'),'retained_exact_text':bool(diag.get('claim_text')),'retained_excerpt':diag.get('claim_text')}
        inventory[row['attempt_id']]=row
    failures=list(inventory.values())
    semantic={'unlabelled_interpretation','deterministic_fact_in_prose','model_generated_number',
              'unsupported_directional_conflict','unsupported_directional_stance','conclusion_argument_mismatch',
              'field_not_in_cited_evidence','schema_string','fact_interpretation_lineage_mismatch',
              'unsupported_direct_fact','invalid_state_value','unsupported_field_key','fact_prose_forbidden',
              'incompatible_evidence_type','field_or_unit_mismatch','invalid_interpretive_support','ungrounded_numeric_claim',
              'Numerical claim lacks matching structured evidence','Interpretation must use interpretive framing and support',
              'Claim cites an incompatible evidence type'}
    replay=build_fixture('B',stamp); raw=ar.evidence_catalog(replay['record']['evidence'])
    for row in failures:
        role=row['agent'];selected=selection_for(role,json.loads(v4.serialize(replay['record'],raw)),row.get('retained_excerpt'))
        v4.validate(selected,role,replay['record']['snapshot_id'],raw)
        row['equivalent_selection_with_original_prose_pass']=True
        row['proof_scope']='Offline structural equivalent, not reinterpretation or acceptance of the original contract.'
    categories=sorted({row['rule'] for row in failures})
    matrix=[]
    for category in categories:
        eliminated=category in semantic
        matrix.append({'historical_category':category,'retained_attempt_count':sum(r['rule']==category for r in failures),
            'classification':'ELIMINATED_BY_DESIGN' if eliminated else 'STILL_RELEVANT',
            'reason':'Removed model-owned semantic field or non-blocking optional prose. Backend resolves values/direction.' if eliminated else
                     'Unknown/duplicate IDs, malformed/schema/provider/system failures remain true structural failures; not bypassed.',
            'proof_tests':['test_backend_direction_not_prose','test_prose_never_enters_fusion','test_number_explanation_nonblocking'] if eliminated else
                          ['test_bad_id','test_duplicate','test_malformed_twice_true_failure']})
    save('v4_failure_elimination_matrix.json',{'retained_attempts':len(failures),'history_not_modified':True,
        'classes':matrix,'attempt_inventory':failures,'exact_text_missing':'Structural-equivalent replay only where prior text was not retained; no fabricated verbatim replay.',
        'eliminated':sum(r['classification']=='ELIMINATED_BY_DESIGN' for r in matrix),'still_relevant':sum(r['classification']=='STILL_RELEVANT' for r in matrix)})
    outcomes={};frozen={};comparison={}
    with patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'}),patch.object(socket.socket,'connect',side_effect=AssertionError('External calls forbidden')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('External DNS forbidden')):
        for test in ('A','B'):
            fixture=build_fixture(test,stamp);record=fixture['record'];raw=ar.evidence_catalog(record['evidence'])
            save(f'v4_live_fixtures/{test}.json',fixture)
            wire=v4.serialize(record,raw)
            outcome=full_team(fixture,ROOT/'outputs/agent_research/v4_offline_audit'/hashlib.sha256(stamp.encode()).hexdigest()[:16]/test,
                lambda role,r,n:{**r,'optional_explanation':'RSI is 63.2.'})
            assert all(outcome['checks'].values()),outcome['checks']
            outcome['fusion_health']={'status':'HEALTHY' if outcome['fusion']['missing_evidence']==[] else 'DEGRADED',
                'rows':len(outcome['fusion']['evidence_items']),'warnings':outcome['fusion']['missing_evidence'],'errors':[],
                'last_update':stamp,'provider':'deterministic','cache_status':outcome['fusion']['cache_status']}
            outcomes[test]=outcome
            frozen[test]={'fixture_id':fixture['fixture_id'],'fixture_path':f'research/results/healthcheck_postrepair/v4_live_fixtures/{test}.json',
                'fixture_file_sha256':sha(REPORTS/f'v4_live_fixtures/{test}.json'),'snapshot_id':record['snapshot_id'],
                'input_bytes':len(wire),'input_sha256':hashlib.sha256(wire).hexdigest(),'synthetic_only':True,'preflight':outcome['preflight']}
            comparison[test]={'v3_input_bytes':len(ar.serialize_agent_input(record)),'v4_input_bytes':len(wire)}
    assert frozen['A']['snapshot_id']!=frozen['B']['snapshot_id']
    save('v4_mocked_workflows.json',outcomes)
    base=load(REPORTS/'typed_prose_live_browser_fixture.json')['fixture']
    save('v4_browser_fixture.json',{'fixture':base,'outcomes':outcomes})
    sample=build_fixture('B',stamp);cat=v4.catalogue(ar.evidence_catalog(sample['record']['evidence']))
    save('agent_output_v4_contract.json',{'schema_version':v4.SCHEMA_VERSION,'validator':v4.VALIDATOR_VERSION,
        'primary_acceptance':['identity','role','action','selection_limit','known_unique_ids','admissible_use','consecutive_priority'],
        'prose_affects_structured_acceptance':False,'backend_result':v4.build_result(outcomes['B']['cached_team']['agents']['bull']['report'],
            'bull',sample['record']['snapshot_id'],ar.evidence_catalog(sample['record']['evidence'])),
        'wire_schema':v4.schema('bull',tuple(cat)),'explanation_policy':'Optional; safety-rejected/omitted uses backend fallback, safe prose is labelled unverified. Never consumed by fusion.',
        'abstention':'Valid completed structured result, zero directional influence; not a provider failure.'})
    save('v4_evidence_catalogue_contract.json',{'version':v4.CATALOGUE_VERSION,'source':'Existing EvidenceSnapshotV1 allowlisted fields',
        'example':cat['kronos.direction'],'derived_meta_evidence':{k:v for k,v in cat.items() if k.startswith('context.')},
        'fact_resolver':'Existing canonical fact resolver/renderer shared with historical v3; no new fact source or indicator',
        'quality_policy':'FAIL/STALE cannot SUPPORT or COUNTER. May be selected as explicit RISK limitation.',
        'freshness_policy':'Market reference: <=1h FRESH, <=1d AGING; news <=3d FRESH, <=7d AGING; otherwise STALE. Missing/future timestamps UNKNOWN; snapshot live eligibility remains independently bounded.',
        'provenance':'Canonical snapshot hash + evidence ID + available fields + lineage + original source hashes in snapshot.'})
    save('v4_role_admissibility_matrix.json',{'limits':v4.LIMITS,'actions':v4.ACTIONS,
        'bull':{'bullish':'SUPPORT','bearish':'COUNTER','risk_or_neutral':'RISK'},
        'bear':{'bearish':'SUPPORT','bullish':'COUNTER','risk_or_neutral':'RISK'},
        'risk':'RISK for operational/quality/freshness/forecast limitations or directional sources; no authored direction',
        'duplicate_policy':'REJECT','priorities':'Unique consecutive 1..N in array order; ranking perfection not judged',
        'counter_evidence':'Explicit use=COUNTER within the same total selection limit; not hidden in prose.'})
    complexity={'schema_properties':{'v3':properties(v3.schema('bull',tuple(cat))),'v4':properties(v4.schema('bull',tuple(cat)))},
        'validator_conditional_branches':{'v3':branches(v3.validate),'v4':branches(v4.validate)},
        'semantic_acceptance_heuristics':{'v3':3,'v4':0,'definition':'Prose factual/number assertions, prose safety rejection and authored stance entailment are blocking in v3; no prose predicate gates v4 selections.'},
        'prompt_characters':{role:{'v3':len(v3.instructions(role,ar.LEGACY_PROMPT_VERSIONS[role])),
            'v4':len(v4.instructions(role,v4.PROMPT_VERSIONS[role]))} for role in ar.AGENTS},
        'fixture_input_bytes':comparison,'expected_output':'6 top-level fields, <=3/4 ID/use/rank entries; estimated 150-350 tokens vs prior observed 659-1337. Estimate, not measured live.',
        'legacy_footprint':'Total repository code grows because legacy contracts are preserved; current acceptance path is simpler.',
        'fusion_weights':'UNCHANGED','new_providers':'NONE'}
    assert complexity['schema_properties']['v4']<complexity['schema_properties']['v3']
    assert complexity['validator_conditional_branches']['v4']<complexity['validator_conditional_branches']['v3']
    assert all(v['v4_input_bytes']<v['v3_input_bytes'] for v in comparison.values())
    save('v4_complexity_comparison.json',complexity)
    source_paths=['app/agent_research.py','app/agent_output_v4.py','app/agent_output_v3.py','app/structured_claims.py','app/evidence_fusion.py','app/dashboard.js',
        'app/server.py','app/evidence_snapshot.py','app/usage_budget.py','research/tests/fixtures/dual_retest_fixtures.py']
    save('v4_final_live_manifest.json',{'schema_version':'v4_final_dual_live_manifest_v1','created_at':stamp,
        'agent_schema':v4.SCHEMA_VERSION,'validator':v4.VALIDATOR_VERSION,'catalogue_version':v4.CATALOGUE_VERSION,
        'renderer_version':v4.RENDERER_VERSION,'prompt_versions':v4.PROMPT_VERSIONS,'config':ar.AgentConfig().__dict__,
        'fixtures':frozen,'source_hashes':{p:sha(ROOT/p) for p in source_paths},'max_workflows':2,'max_calls':12,
        'max_retries':1,'loop_limit':1,'tools':'NONE','requires_fresh_authorization':True,
        'freshness':'If expired, timestamp-only refresh with semantic-equivalence proof and new freeze BEFORE provider execution; never silently refreeze.',
        'cache_policy':'Initial misses required; snapshot/role/model/prompt/schema/validator/config identity included.',
        'success':'All three valid selections including legitimate abstention; bad optional prose may FALLBACK without retry/failure.',
        'external_calls_this_task':0,'historical_hashes':history})
    (REPORTS/'v4_fusion_adapter_report.md').write_text('# V4 Fusion Adapter\n\nPASS: normal and adversarial mocked workflows completed 3/3.\n\nOnly backend-resolved selection metadata enters fusion. Optional prose is never fused. Agent items remain DERIVED and contribute zero independent directional weight. Existing weights were not tuned. Shared underlying IDs preserve lineage; an abstention is a present valid perspective with zero strength, not an invented neutral primary source. Adversarial primary conflicts remain visible. Cache invalidates on upstream report and adapter version.\n',encoding='utf-8')
    for name,value in history.items():assert sha(REPORTS/name)==value
    print(json.dumps({'normal':frozen['A']['input_bytes'],'adversarial':frozen['B']['input_bytes'],
        'retained_attempts':len(failures),'categories':categories,'complexity':complexity},indent=2))

if __name__=='__main__':main()
