"""Build offline v3 audit artifacts; never constructs a live provider client."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import socket
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import agent_research as ar, agent_output_v3 as v3
from app.evidence_snapshot import canonical_bytes
from research.tests.fixtures.dual_retest_fixtures import build_fixture
from research.tests.test_agent_output_v3 import full_team, report_for

REPORTS = ROOT / 'research/results/healthcheck_postrepair'


def save(name, value):
    path = REPORTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay_history():
    sources = ['live_three_agent_confirmation.json', 'live_retest_A_production.json',
               'final_live_A.json', 'final_live_B.json']
    attempts = {}
    for source in sources:
        document = json.loads((REPORTS / source).read_text())
        for attempt in document.get('attempt_records', []):
            attempts[attempt['attempt_id']] = (attempt, source)
    # Earlier Phase 7 ledgers may retain additional bounded rejected-claim diagnostics.
    for path in (ROOT / 'outputs/agent_research').rglob('attempts/*.json'):
        row = json.loads(path.read_text())
        if row.get('status') == 'FAILED' and row.get('validation_diagnostic') and \
                not str(row.get('request_id') or '').startswith('req_offline') and \
                row.get('attempt_id') not in attempts:
            attempts[row['attempt_id']] = (row, path.relative_to(ROOT).as_posix())
    cases = []
    stamp = '2026-10-09T15:18:00+00:00'
    for attempt_id, (row, source) in sorted(attempts.items()):
        diagnostic = row.get('validation_diagnostic') or {}
        if not diagnostic:
            continue
        # Only sanitized retained shapes exist; do not reconstruct rejected full outputs.
        role = row.get('agent_type') or diagnostic.get('agent')
        record = build_fixture('B' if row.get('test_id') == 'B' else 'A', stamp)['record']
        catalog = ar.evidence_catalog(record['evidence'])
        refs = diagnostic.get('evidence_ids') or []
        pairs = [pair for pair in v3.fact_catalog(catalog) if pair['evidence_id'] in refs]
        structured = diagnostic.get('structured_fact') or {}
        key = structured.get('field_key')
        if key:
            canonical = ar.ALIASES.get(key, key)  # Historical audit translation ONLY, not v3 validation.
            chosen = [p for p in pairs if p['field_key'] == canonical]
            pairs = chosen or pairs
        corrected = report_for(role, record)
        if not pairs:
            # Legacy numerical diagnostics may use a distinct key for cited evidence.
            refs = diagnostic.get('claim_evidence_ids') or refs
            pairs = [pair for pair in v3.fact_catalog(catalog) if pair['evidence_id'] in refs]
        correction_tested = bool(pairs)
        if pairs:
            pairs = pairs[:8]
            corrected['stance'] = 'RISK' if role == 'risk' else 'UNCERTAIN'
            corrected['arguments'] = [{'argument_id':'A1', 'stance':corrected['stance'],
                'evidence_fact_refs':pairs, 'support_level':'LOW',
                'interpretation':{'claim_type':'INTERPRETATION', 'support_type':'INTERPRETIVE',
                    'text':'Cited evidence may support a cautious interpretation; uncertainty remains.',
                    'evidence_ids':sorted(set(refs).intersection(k for k,v in catalog.items() if v is not None) |
                                          {p['evidence_id'] for p in pairs})}}]
            v3.validate(corrected, role, record['snapshot_id'], catalog)
            v3.presentation(corrected, catalog)
        original = copy.deepcopy(corrected)
        arg = original['arguments'][0]
        # Replay the retained wrong ownership at the new boundary, not a sentence whitelist.
        if structured:
            arg['evidence_fact_refs'][0].update({k:v for k,v in structured.items() if k in {'value','unit','direction'}})
        else:
            arg['interpretation']['claim_type'] = diagnostic.get('claim_type') or 'FACT'
            arg['interpretation']['support_type'] = diagnostic.get('support_type') or 'DIRECT'
            arg['interpretation']['text'] = diagnostic.get('claim_text') or 'Unsupported 15% interpretation.'
        rejected = False
        try:
            v3.validate(original, role, record['snapshot_id'], catalog)
        except v3.ContractError:
            rejected = True
        if not rejected:
            # An old cross-family interpretation is legitimate in v3. The caller declares no fake family.
            arg['interpretation']['support_type'] = 'DIRECT'
            try: v3.validate(original, role, record['snapshot_id'], catalog)
            except v3.ContractError: rejected = True
        cases.append({'attempt_id':attempt_id, 'source':source, 'agent':role, 'attempt':row.get('attempt'),
            'historical_snapshot_id':row.get('snapshot_id'), 'retained_diagnostic':diagnostic,
            'offline_replay_snapshot_id':record['snapshot_id'],
            'historical_rejection':row.get('sanitized_error') or diagnostic.get('failure_reason'),
            'ownership_violation_rejected':rejected, 'backend_owned_equivalent_pass':correction_tested,
            'canonical_fact_refs':pairs,
            'scope':'Offline-authored structural equivalent. Not a regenerated model response or reconstruction of discarded output.'})
    return {'schema_version':'v3_live_failure_replay_v1', 'cases':cases, 'case_count':len(cases),
        'status':'PASS' if cases and all(c['ownership_violation_rejected'] and c['backend_owned_equivalent_pass'] for c in cases) else 'PARTIAL',
        'historical_failure_counts':dict(Counter(c['historical_rejection'] for c in cases)),
        'source_hashes':{s:file_hash(REPORTS/s) for s in sources}, 'external_calls':0,
        'limitation':'Historical API failures without retained claim diagnostics are not claim replays. Existing mocked response-stage tests cover them.'}


def build():
    stamp = datetime.now(timezone.utc).isoformat()
    fixtures = {test:build_fixture(test,stamp) for test in ('A','B')}
    outcomes = {}
    frozen = {}
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Network prohibited')), \
         patch.object(socket,'getaddrinfo',side_effect=AssertionError('Network prohibited')), \
         patch.dict(os.environ,{'OPENAI_API_KEY':'offline-v3-audit-only'}):
        for test,fixture in fixtures.items():
            outcomes[test] = full_team(fixture, ROOT / 'outputs/agent_research/v3_offline' / hashlib.sha256(stamp.encode()).hexdigest()[:12] / test)
            assert all(outcomes[test]['checks'].values()), outcomes[test]['checks']
            save(f'v3_offline_{test}.json',outcomes[test])
            save(f'v3_fixtures/{test}.json',fixture)
            path = REPORTS / f'v3_fixtures/{test}.json'
            wire = ar.serialize_agent_input(fixture['record'])
            estimates = {}
            for role in ar.AGENTS:
                output = canonical_bytes(report_for(role,fixture['record']))
                estimates[role] = {'json_bytes':len(output), 'estimated_tokens':(len(output)+3)//4,
                    'method':'UTF-8 bytes divided by four, rounded up. Heuristic only; no tokenizer or measured API usage.'}
            frozen[test] = {'fixture_id':fixture['fixture_id'], 'fixture_path':path.relative_to(ROOT).as_posix(),
                'fixture_file_sha256':file_hash(path), 'snapshot_id':fixture['record']['snapshot_id'],
                'input_bytes':len(wire), 'input_sha256':hashlib.sha256(wire).hexdigest(),
                'input_headroom_bytes':48000-len(wire), 'preflight':outcomes[test]['preflight'],
                'offline_checks':outcomes[test]['checks'], 'offline_output_estimates':estimates,
                'future_live_cache_scope':f'outputs/agent_research/v3_live/{test}',
                'mock_cache_scope':'outputs/agent_research/v3_offline', 'future_live_cache_miss_required':True}
    replay = replay_history(); save('v3_live_failure_replay.json',replay)
    sample = ar.evidence_catalog(fixtures['A']['record']['evidence'])
    contract = {'schema_version':v3.SCHEMA_VERSION,'validator_version':v3.VALIDATOR_VERSION,
        'fact_ownership':'BACKEND','fact_ref_keys':['evidence_id','field_key'],'model_values_and_units':False,
        'canonical_fields':list(v3.CANONICAL_FIELDS),'role_stances':v3.STANCES,'support_levels':v3.SUPPORT,
        'interpretations':'INTERPRETATION / INTERPRETIVE, number-free, cited, cautious, separate from facts',
        'fact_source_family':'Derived from exact evidence ID and binding; never supplied by model',
        'interpretation_support_families':'Derived from all citations; legitimate multi-family synthesis allowed',
        'strict_schema_examples':{role:v3.schema(role,ar.allowed_evidence_ids(sample)) for role in ar.AGENTS},
        'limitations':['Bounded deterministic guards are not universal NLP semantic entailment.',
            'Qualitative support labels are not calibrated probabilities.','Live provider v3 behavior not yet tested.']}
    save('agent_output_v3_contract.json',contract)
    save('deterministic_fact_renderer.json',{'version':v3.RENDERER_VERSION,
        'ownership':'Backend resolves existing field_bindings; v3 rejects aliases and model values/units.',
        'format_policy':'Preserve canonical raw values; percentages retain sign; prices use native quote units, never inferred currency.',
        'examples':[v3.render_fact(ref,sample) for ref in v3.fact_catalog(sample)],
        'unknown_or_unsafe_binding':'REJECT','source_reference_preserved':True})
    sources = ['app/agent_output_v3.py','app/agent_research.py','app/evidence_fusion.py','app/dashboard.js',
               'app/structured_claims.py','app/evidence_snapshot.py','app/security.py','app/server.py',
               'app/usage_budget.py','research/tests/fixtures/dual_retest_fixtures.py']
    save('v3_live_retest_manifest.json',{'schema_version':'v3_dual_live_manifest_v1', 'frozen_at':stamp,
        'agent_schema':v3.SCHEMA_VERSION,'validator':v3.VALIDATOR_VERSION,'renderer':v3.RENDERER_VERSION,
        'prompt_versions':ar.PROMPT_VERSIONS,'model':'gpt-5-mini','max_input_bytes':48000,'max_output_tokens':1600,
        'loop_limit':1,'retry_limit':1,'tools':'NONE','daily_call_limit':12,'max_workflows':2,'max_live_calls':12,
        'live_authorized':False,'live_executed':False,'fixtures':frozen,
        'expires_at':(datetime.fromisoformat(stamp)+timedelta(hours=1)).isoformat(),
        'execution_conditions':['Fresh explicit authorization required.','All fixture/source hashes must match.',
            'Existing one-hour snapshot/acquisition freshness guard must pass.',
            'If expired, separately authorize a timestamp-only fresh freeze; never silently edit fixtures.',
            'Use an empty live cache namespace, never the offline mock namespace.',
            'Daily persisted production budget must have sufficient allowance; do not reset or override it.',
            'Stop on failed preflight; no diagnostic calls or contract edits during execution.'],
        'source_hashes':{source:file_hash(ROOT/source) for source in sources},'monad_permission':False})
    base = json.loads((REPORTS/'structured_claim_browser_fixture.json').read_text())
    save('v3_browser_fixture.json',{'fixture':base['fixture'],'outcomes':outcomes})
    print(json.dumps({'offline_teams':{t:o['checks'] for t,o in outcomes.items()},'history_cases':len(replay['cases']),
        'replay':replay['status'],'input_bytes':{t:f['input_bytes'] for t,f in frozen.items()},'external_calls':0}))


if __name__ == '__main__': build()
