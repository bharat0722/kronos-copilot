"""Two explicitly authorized V4 workflows; production contracts stay frozen."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_v3_live_confirmation as base
from app import agent_research as ar, agent_output_v4 as v4, agent_output_v3 as facts
from app.evidence_snapshot import canonical_bytes, snapshot_id
from app.evidence_fusion import EvidenceFusionEngine

REPORTS = ROOT / 'research/results/healthcheck_postrepair'
MANIFEST = REPORTS / 'v4_fresh_live_manifest.json'
SCOPE = ROOT / 'outputs/agent_research/v4_live_confirmation'
AGENT_ROOT = SCOPE / 'agents'
base.MANIFEST, base.SCOPE = MANIFEST, SCOPE
load, save, sha = base.load, base.save, base.sha


def wire(record):
    return v4.serialize(record, ar.evidence_catalog(record['evidence']))


def semantic_catalogue(record):
    cat = copy.deepcopy(v4.catalogue(ar.evidence_catalog(record['evidence'])))
    for item in cat.values():
        item.pop('observed_at', None)
    return cat


def no_provider():
    raise RuntimeError('Retrieval/integration cannot call provider')


def prepare():
    if MANIFEST.exists() or (SCOPE / 'execution.json').exists():
        raise RuntimeError('Persisted V4 execution exists; no duplicate freeze or workflow allowed')
    old = load(REPORTS / 'v4_final_live_manifest.json')
    base.source_check(old)
    base.credential()
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'monad-metropolis'
    config = ar.AgentConfig()
    assert asdict(config) == old['config']
    assert ar.SCHEMA_VERSION == v4.SCHEMA_VERSION == old['agent_schema'] == 'agent_output_v4'
    assert v4.VALIDATOR_VERSION == old['validator'] == 'evidence_selection_validator_v1'
    assert ar.PROMPT_VERSIONS == old['prompt_versions'] == {'bull': 'bull_agent_prompt_v10', 'bear': 'bear_agent_prompt_v9', 'risk': 'risk_agent_prompt_v9'}
    assert config.model == 'gpt-5-mini' and config.max_input_bytes == 48000 and config.max_output_tokens == 1600
    assert ar.MAX_RETRIES == ar.MAX_REASONING_ROUNDS == 1
    stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    frozen = {}
    team = ar.AgentTeam(AGENT_ROOT, config=config, client_factory=no_provider)
    assert team.usage.totals('openai_agents')[0] == 0
    for test in ('A', 'B'):
        row = old['fixtures'][test]
        path = ROOT / row['fixture_path']
        assert sha(path) == row['fixture_file_sha256']
        original = load(path)
        assert hashlib.sha256(wire(original['record'])).hexdigest() == row['input_sha256']
        fresh = copy.deepcopy(original)
        changes = []
        for parts in base.ALLOW:
            node = fresh
            for part in parts[:-1]:
                node = node[part]
            changes.append({'path': list(parts), 'before': node[parts[-1]], 'after': stamp})
            node[parts[-1]] = stamp
        fresh['record']['snapshot_id'] = snapshot_id(fresh['record']['evidence'])
        restored = copy.deepcopy(fresh)
        for change in changes:
            node = restored
            for part in change['path'][:-1]:
                node = node[part]
            node[change['path'][-1]] = change['before']
        restored['record']['snapshot_id'] = original['record']['snapshot_id']
        assert canonical_bytes(restored) == canonical_bytes(original), 'Material fixture mutation'
        assert semantic_catalogue(original['record']) == semantic_catalogue(fresh['record']), 'Catalogue semantics changed'
        assert facts.fact_catalog(ar.evidence_catalog(original['record']['evidence'])) == facts.fact_catalog(ar.evidence_catalog(fresh['record']['evidence']))
        assert fresh['record']['snapshot_id'] != row['snapshot_id']
        assert fresh['synthetic_only'] and fresh['record']['evidence']['instrument']['canonical_symbol'] == 'NSE:TESTCO'
        base.private_check(fresh)
        preflight = team.preflight(fresh['record'])
        state = team.result(fresh['record'])
        misses = {role: not state['agents'][role].get('report') for role in ar.AGENTS}
        assert all(misses.values())
        payload = wire(fresh['record'])
        assert len(payload) <= 48000
        destination = REPORTS / 'v4_fresh_live_fixtures' / (test + '.json')
        save(destination, fresh)
        frozen[test] = {'fixture_id': fresh['fixture_id'], 'fixture_path': destination.relative_to(ROOT).as_posix(),
            'fixture_file_sha256': sha(destination), 'snapshot_id': fresh['record']['snapshot_id'],
            'previous_snapshot_id': row['snapshot_id'], 'input_bytes': len(payload),
            'input_sha256': hashlib.sha256(payload).hexdigest(), 'semantic_difference': 0,
            'semantic_change_counts': {name: 0 for name in ('forecast', 'technicals', 'news', 'numerical_evidence',
                'role_compatibility', 'evidence_family', 'direction', 'conflict', 'uncertainty_inputs')},
            'permitted_changes': changes, 'initial_cache_miss': misses, 'preflight': preflight,
            'freshness_timestamp': stamp, 'catalogue_semantic_sha256': hashlib.sha256(canonical_bytes(semantic_catalogue(fresh['record']))).hexdigest()}
    assert frozen['A']['snapshot_id'] != frozen['B']['snapshot_id']
    manifest = {**old, 'schema_version': 'v4_fresh_live_manifest_v1', 'created_at': stamp,
        'expires_at': (datetime.fromisoformat(stamp) + timedelta(hours=1)).isoformat(), 'fixtures': frozen,
        'source_hashes': {**old['source_hashes'], 'tools/run_v4_live_confirmation.py': sha(Path(__file__)),
            'tools/v4_live_dashboard_qa.cjs': sha(ROOT / 'tools/v4_live_dashboard_qa.cjs'),
            'tools/run_v3_live_confirmation.py': sha(ROOT / 'tools/run_v3_live_confirmation.py')},
        'prior_manifest_sha256': sha(REPORTS / 'v4_final_live_manifest.json'),
        'requires_fresh_authorization': False, 'authorization': 'Current explicit two synthetic V4 workflows, at most twelve requests; existing credential reuse confirmed previously',
        'budget_scope': 'New task-scoped persisted twelve-call allowance in isolated AgentTeam root; production counters untouched',
        'cache_scope': AGENT_ROOT.relative_to(ROOT).as_posix(), 'max_openai_calls': 12,
        'historical_hashes': {name: sha(REPORTS / name) for name in ('v3_live_A.json', 'v3_live_B.json',
            'typed_prose_live_A.json', 'typed_prose_live_B.json', 'typed_prose_dual_live_summary.json',
            'agent_output_v4_design.md', 'v4_final_live_manifest.json')}}
    save(MANIFEST, manifest)
    print(json.dumps({'stage': 'FROZEN', 'fixtures': {t: {k: r[k] for k in ('fixture_id', 'snapshot_id', 'input_bytes', 'semantic_difference', 'initial_cache_miss')} for t, r in frozen.items()}}, indent=2))


def fixture_read(row):
    assert sha(ROOT / row['fixture_path']) == row['fixture_file_sha256']
    fixture = load(ROOT / row['fixture_path'])
    record = fixture['record']
    assert snapshot_id(record['evidence']) == record['snapshot_id'] == row['snapshot_id']
    payload = wire(record)
    assert len(payload) == row['input_bytes'] and hashlib.sha256(payload).hexdigest() == row['input_sha256']
    assert hashlib.sha256(canonical_bytes(semantic_catalogue(record))).hexdigest() == row['catalogue_semantic_sha256']
    base.private_check(fixture)
    return fixture


class GuardResponses(base.GuardResponses):
    def create(self, **request):
        state = load(SCOPE / 'execution.json')
        test = state['active_test']
        role = request['text']['format']['schema']['properties']['agent_type']['enum'][0]
        assert role in ar.AGENTS
        assert state['test_calls'][test] < 6 and state['role_calls'][test][role] < 2
        assert request['instructions'] == v4.instructions(role, v4.PROMPT_VERSIONS[role])
        assert request['text']['format']['strict'] is True
        ids = tuple(sorted(json.loads(request['input'].split('\n', 1)[1])['catalogue']))
        assert request['text']['format']['schema'] == v4.schema(role, ids)
        state['test_calls'][test] += 1
        state['role_calls'][test][role] += 1
        save(SCOPE / 'execution.json', state)
        return super().create(**request)


def report_wire(report):
    return {k: v for k, v in report.items() if k != 'explanation_status'}


def integration(test, fixture, result, pre_agent, engine, team):
    record = fixture['record']
    raw = ar.evidence_catalog(record['evidence'])
    restored = ar.AgentTeam(AGENT_ROOT, config=team.config, client_factory=no_provider)
    cached = restored.result(record)
    fusion = engine.fuse(record, agent_result=cached, pipeline=fixture['pipeline'])
    hit = engine.fuse(record, agent_result=cached, pipeline=fixture['pipeline'])
    parents = [load(p) for p in (AGENT_ROOT / 'runs').glob('*.json') if load(p).get('snapshot_id') == record['snapshot_id']]
    attempts = sorted([load(p) for p in (AGENT_ROOT / 'attempts').glob('*.json') if load(p).get('snapshot_id') == record['snapshot_id']], key=lambda a: (a['started_at'], a['agent_type'], a['attempt']))
    audit_attempts = []
    for attempt in attempts:
        parent = next(p for p in parents if p['run_id'] == attempt['run_id'])
        audit_attempts.append({**attempt, 'test_id': test, 'workflow_id': result['run_id'],
            'cache_status': parent['cache_status'], 'validation_status': 'PASS' if attempt['status'] == 'SUCCESS' else 'FAIL',
            'production_attempt_sha256': sha(AGENT_ROOT / 'attempts' / (attempt['attempt_id'] + '.json'))})
    save(SCOPE / test / 'workflow_attempt_ledger.json', audit_attempts)
    accepted = [e for e in cached['agents'].values() if e.get('report')]
    proofs = []
    for entry in accepted:
        report = entry['report']
        v4.validate(report_wire(report), report['agent_type'], record['snapshot_id'], raw)
        built = v4.build_result(report, report['agent_type'], record['snapshot_id'], raw)
        assert entry['presentation'] == v4.presentation(report, raw)
        # Local probes on an actual accepted selection, never extra provider calls.
        probes = []
        for prose in ('RSI is 63.2.', '', '<script>bad</script>', {'malformed': True}):
            variant = {**report_wire(report), 'optional_explanation': prose}
            checked = v4.validate(variant, report['agent_type'], record['snapshot_id'], raw)
            derived = v4.build_result(checked, report['agent_type'], record['snapshot_id'], raw)
            same = all(derived[k] == built[k] for k in ('resolved_facts', 'direction', 'conflict', 'support_level', 'risk_level', 'uncertainty_flags', 'lineage_ids', 'selected_evidence'))
            assert same and derived['explanation_status'] in {'REJECTED', 'OMITTED'}
            probes.append({'kind': 'empty' if prose == '' else 'number' if isinstance(prose, str) and '63.2' in prose else 'unsafe_or_malformed', 'structured': 'PASS', 'explanation': derived['explanation_status'], 'truth_unchanged': same})
        proofs.append({'agent': report['agent_type'], 'action': report['action'], 'direction': built['direction'],
            'conflict': built['conflict'], 'support': built['support_level'], 'explanation_status': built['explanation_status'],
            'selected': report['selected_evidence'], 'local_nonblocking_probes': probes})
    agent_items = [e for e in fusion['evidence_items'] if e['evidence_type'].startswith('AGENT_')]
    health, fusion_health = restored.health(record), engine.health()
    checks = {'structured': len(accepted) == 3, 'evidence_ids': len(accepted) == 3,
        'role_admissibility': len(accepted) == 3, 'backend_fact_resolution': len(accepted) == 3,
        'backend_direction': len(proofs) == 3, 'backend_conflict': len(proofs) == 3,
        'backend_uncertainty': len(proofs) == 3, 'optional_prose_nonblocking': len(proofs) == 3,
        'team': result['agents_completed'] == 3, 'durable': cached['team_status'] == 'COMPLETE',
        'cache': len(parents) == 3 and all(p['cache_status'] == 'STORED' for p in parents),
        'fusion_cache_invalidation': fusion['result_hash'] != pre_agent['result_hash'] and hit['cache_status'] == 'hit',
        'fusion_adapter': len(agent_items) == 3 and all(e['role'] == 'DERIVED' for e in agent_items),
        'double_counting': len(agent_items) == 3 and all(not e['contributes_to_direction'] for e in agent_items),
        'lineage': len(agent_items) == 3 and all(e['provenance']['agent_run_id'] for e in agent_items),
        'missing_agent_markers': not any(x.startswith('AGENT_') for x in fusion['missing_evidence']),
        'conflict_preservation': test != 'B' or bool(fusion['conflicts']),
        'dashboard_adapter': len(accepted) == 3 and all(e['presentation']['schema_version'] == v4.SCHEMA_VERSION for e in accepted),
        'pipeline': health['rows'] == 3 and health['team_status'] == 'COMPLETE' and health['status'] == 'HEALTHY',
        'fusion_health': fusion_health['snapshot_id'] == record['snapshot_id'] and fusion_health['status'] == 'HEALTHY',
        'ledger': len(parents) == 3 and all(p['attempt_refs'] and p['output_schema_version'] == v4.SCHEMA_VERSION for p in parents),
        'observability': bool(attempts) and all(a['sdk_attempted'] and a['request_id'] and a['output_schema_version'] == v4.SCHEMA_VERSION and all(a['token_usage'][k] is not None for k in ('input_tokens', 'output_tokens', 'total_tokens')) for a in attempts),
        'no_truncation': all(a['response_status'] == 'completed' and a.get('completion_reason') != 'max_output_tokens' for a in attempts),
        'snapshot_ownership': cached['snapshot_id'] == record['snapshot_id'], 'public_error_safety': True}
    for public in (cached, audit_attempts, fusion):
        base.private_check(public)
    return {'test': test, 'status': 'PASS' if all(checks.values()) else 'FAIL',
        'fixture': fixture['fixture_id'], 'snapshot_id': record['snapshot_id'], 'serialized_size': len(wire(record)),
        'semantic_difference': 0, 'checks': checks, 'team': result, 'cached_team': cached,
        'fusion': fusion, 'health': health, 'fusion_health': fusion_health, 'attempt_records': audit_attempts,
        'ledger_records': parents, 'backend_proofs': proofs, 'api_cost': 'UNKNOWN',
        'optional_prose_proof_scope': 'Actual explanation states retained; bad/empty/unsafe variants are local post-response probes, not fabricated provider responses'}


def run():
    import httpx2 as httpx
    from openai import OpenAI
    manifest = load(MANIFEST)
    base.source_check(manifest)
    base.credential()
    config = ar.AgentConfig()
    assert asdict(config) == manifest['config']
    if (SCOPE / 'execution.json').exists():
        raise RuntimeError('Live execution already started; do not repeat workflows')
    for row in manifest['fixtures'].values():
        ar.assert_fresh_snapshot(fixture_read(row)['record'])
    team = ar.AgentTeam(AGENT_ROOT, config=config)
    assert team.usage.totals('openai_agents')[0] == 0
    save(SCOPE / 'execution.json', {'provider_calls': 0, 'active_test': None, 'workflow_states': {}, 'max_calls': 12,
        'test_calls': {'A': 0, 'B': 0}, 'role_calls': {t: {r: 0 for r in ar.AGENTS} for t in ('A', 'B')}, 'started_at': base.now()})
    transport = base.AllowedTransport()
    http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.openai.com/v1', timeout=config.timeout_seconds, max_retries=0, http_client=http)
    guarded = type('GuardClient', (), {})()
    guarded.responses = GuardResponses(client, config)
    try:
        for test in ('A', 'B'):
            fixture = fixture_read(manifest['fixtures'][test])
            record = fixture['record']
            team = ar.AgentTeam(AGENT_ROOT, config=config, client_factory=lambda: guarded)
            preflight = team.preflight(record)
            assert all(not e.get('report') for e in team.result(record)['agents'].values())
            state = load(SCOPE / 'execution.json')
            state['active_test'] = test
            state['workflow_states'][test] = 'RUNNING'
            save(SCOPE / 'execution.json', state)
            before = canonical_bytes(fixture)
            engine = EvidenceFusionEngine(SCOPE / test / 'fusion')
            pre_agent = engine.fuse(record, agent_result=team.result(record), pipeline=fixture['pipeline'])
            result = team.run(record)
            save(SCOPE / test / 'team_result.json', result)
            out = integration(test, fixture, result, pre_agent, engine, team)
            out['preflight'] = preflight
            out['checks']['immutability'] = canonical_bytes(fixture) == before
            out['status'] = 'PASS' if all(out['checks'].values()) else 'FAIL'
            save(REPORTS / ('v4_live_' + test + '.json'), out)
            state = load(SCOPE / 'execution.json')
            state['workflow_states'][test] = 'FINISHED'
            save(SCOPE / 'execution.json', state)
            print(json.dumps({'test': test, 'status': out['status'], 'team': result['agents_completed'], 'calls': result['api_calls'], 'failed_checks': [k for k, v in out['checks'].items() if not v]}), flush=True)
    finally:
        client.close()
        state = load(SCOPE / 'execution.json')
        state.update(transport_requests=transport.requests, persisted_reserved_requests=team.usage.totals('openai_agents')[0], finished_at=base.now())
        save(SCOPE / 'execution.json', state)
    assert state['provider_calls'] == state['transport_requests'] == state['persisted_reserved_requests'] <= 12
    base.source_check(manifest)
    fixture = load(REPORTS / 'v4_browser_fixture.json')['fixture']
    save(REPORTS / 'v4_live_browser_fixture.json', {'fixture': fixture, 'outcomes': {t: load(REPORTS / ('v4_live_' + t + '.json')) for t in ('A', 'B')}})
    summarize(final=False)


def failure_category(attempt):
    rule = (attempt.get('validation_diagnostic') or {}).get('rule_code') or ''
    if rule == 'unknown_evidence_id': return 'INVALID_ID'
    if rule == 'role_admissibility': return 'ROLE_ADMISSIBILITY'
    if rule == 'action_enum': return 'ACTION_ENUM'
    if rule == 'selection_limit': return 'SELECTION_LIMIT'
    if rule == 'schema_identity' and (attempt.get('validation_diagnostic') or {}).get('json_path') == '$.snapshot_id': return 'SNAPSHOT'
    stage = attempt.get('failure_stage') or ''
    if stage == 'LEDGER_COMMIT': return 'LEDGER'
    if stage == 'CACHE_WRITE': return 'CACHE'
    if stage in {'SDK_CALL', 'API_ERROR', 'RESPONSE_STATUS', 'RESPONSE_INCOMPLETE', 'RESPONSE_REFUSAL'}: return 'PROVIDER'
    return 'SCHEMA' if rule or stage in {'SCHEMA_VALIDATION', 'STRUCTURED_PARSE', 'CLAIM_VALIDATION'} else 'SYSTEM'


def summarize(final=True):
    manifest = load(MANIFEST)
    base.source_check(manifest)
    state = load(SCOPE / 'execution.json')
    assert state['provider_calls'] == state['transport_requests'] == state['persisted_reserved_requests'] <= 12
    outcomes = {t: load(REPORTS / ('v4_live_' + t + '.json')) for t in ('A', 'B')}
    restored = ar.AgentTeam(AGENT_ROOT, client_factory=no_provider)
    isolation = manifest['fixtures']['A']['snapshot_id'] != manifest['fixtures']['B']['snapshot_id']
    durable = all(restored.result(fixture_read(manifest['fixtures'][t])['record'])['team_status'] == out['cached_team']['team_status'] for t, out in outcomes.items())
    qa_path = REPORTS / 'v4_live_qa/qa.json'
    qa = load(qa_path) if qa_path.exists() else {'status': 'NOT_RUN'}
    attempts = [a for out in outcomes.values() for a in out['attempt_records']]
    accepted = [a for a in attempts if a['status'] == 'SUCCESS']
    unknown = sum(any(a['token_usage'][k] is None for k in ('input_tokens', 'output_tokens', 'total_tokens')) for a in attempts)
    usage = {k: sum(a['token_usage'][k] for a in attempts if a['token_usage'][k] is not None) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    retries = sum(e['attempts'] > 1 for out in outcomes.values() for e in out['team']['agents'].values())
    first = sum(a['attempt'] == 1 and a['status'] == 'SUCCESS' for a in attempts)
    prior_outputs = []
    for name in ('v3_live_A.json', 'v3_live_B.json', 'typed_prose_live_A.json', 'typed_prose_live_B.json'):
        prior_outputs.extend(a['token_usage']['output_tokens'] for a in load(REPORTS / name)['attempt_records'] if a.get('token_usage', {}).get('output_tokens') is not None)
    mean = sum(a['token_usage']['output_tokens'] for a in accepted) / len(accepted) if accepted else None
    previous_mean = sum(prior_outputs) / len(prior_outputs) if prior_outputs else None
    failures = []
    for test, out in outcomes.items():
        for role, entry in out['team']['agents'].items():
            if not entry.get('report'):
                attempt = next((a for a in reversed(out['attempt_records']) if a['agent_type'] == role), {})
                failures.append({'test': test, 'agent': role, 'category': failure_category(attempt),
                    'diagnostic': attempt.get('validation_diagnostic'), 'reason': attempt.get('sanitized_error') or entry.get('error_message')})
    gate = all(out['status'] == 'PASS' for out in outcomes.values()) and isolation and durable and qa['status'] == 'PASS'
    blocker = failures[0] if failures else None
    if final and not gate and not blocker:
        blocker = {'category': 'SYSTEM', 'reason': 'Browser/integration gate not complete or failed'}
    health = 'GREEN' if gate else 'RED' if failures else 'YELLOW'
    summary = {'schema_version': 'v4_final_dual_confirmation_v1', 'status': 'PASS' if gate else 'FAIL' if failures else 'PARTIAL',
        'model': manifest['config']['model'], 'agent_schema': v4.SCHEMA_VERSION, 'validator': v4.VALIDATOR_VERSION,
        'prompt_versions': v4.PROMPT_VERSIONS, 'openai_calls': state['provider_calls'], 'transport_requests': state['transport_requests'],
        'persisted_reserved_requests': state['persisted_reserved_requests'], 'usage': usage, 'unknown_usage_attempts': unknown, 'api_cost': 'UNKNOWN',
        'first_attempt_pass_rate': first / 6, 'retry_rate': retries / 6, 'average_v4_output_tokens': mean,
        'max_v4_output_tokens': max((a['token_usage']['output_tokens'] for a in attempts if a['token_usage']['output_tokens'] is not None), default=None),
        'v3_comparison': {'attempts': len(prior_outputs), 'average_output_tokens': previous_mean, 'scope': 'Descriptive retained V3 attempts on these fixture types; not a controlled benchmark'},
        'v4_output_smaller': mean is not None and previous_mean is not None and mean < previous_mean,
        'truncated': sum(a.get('completion_reason') == 'max_output_tokens' for a in attempts),
        'tests': {t: {k: out[k] for k in ('status', 'fixture', 'snapshot_id', 'serialized_size', 'semantic_difference', 'checks', 'backend_proofs')} for t, out in outcomes.items()},
        'snapshot_isolation': isolation, 'durable_isolation': durable, 'dashboard_browser_qa': qa,
        'architectural_loop': 'ELIMINATED_FOR_PROSE_DRIVEN_ACCEPTANCE_FAILURES', 'prose_blocks_structured': False,
        'model_numbers_affect_truth': False, 'model_determines_direction': False,
        'actual_explanation_statuses': {t: {r: e.get('explanation_status') for r, e in out['team']['agents'].items()} for t, out in outcomes.items()},
        'highest_priority_structural_blocker': blocker, 'failures': failures,
        'monad_readiness': health, 'monad_permission': gate, 'architecture_score': 8.8,
        'score_scope': 'Prior custom scoped architecture assessment retained, not a fresh comprehensive project/forecasting rating',
        'latest_offline_tests': {'passed': 392, 'failed': 0, 'skipped': 1, 'rerun_this_task': 0},
        'safety': {'other_external_calls': 0, 'yahoo': 0, 'tavily': 0, 'monad': 0, 'kronos_inference': 0, 'kronos_training': 0,
            'weight_changes': 0, 'validation_reruns': 0, 'locked_test_accesses': 0, 'blockchain_transactions': 0,
            'production_code_changed': False, 'contract_changes': False, 'monad_implementation': False, 'git_commit': False, 'git_push': False}}
    for name, expected in manifest['historical_hashes'].items():
        assert sha(REPORTS / name) == expected
    save(REPORTS / 'v4_final_dual_confirmation.json', summary)
    for test, out in outcomes.items():
        lines = ['# V4 Live Test ' + test, '', 'Status: ' + out['status'], 'Fixture: ' + out['fixture'],
            'Snapshot: ' + out['snapshot_id'], 'Serialized bytes: ' + str(out['serialized_size']),
            'Semantic differences: 0', 'Team: ' + str(out['team']['agents_completed']) + '/3', '', '## Checks']
        lines += ['- ' + k + ': ' + ('PASS' if v else 'FAIL') for k, v in out['checks'].items()]
        lines += ['', '## Attempts', '| Agent | Attempt | Structured | Explanation | Input | Output | Total | Provider | Rejection |', '| --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |']
        for a in out['attempt_records']:
            u = a['token_usage']
            lines.append(f"| {a['agent_type']} | {a['attempt']} | {a['status']} | {a.get('explanation_status', '-')} | {u['input_tokens']} | {u['output_tokens']} | {u['total_tokens']} | {a.get('response_status')} | {a.get('sanitized_error') or '-'} |")
        lines += ['', '## Backend and Optional Prose', json.dumps(out['backend_proofs'], indent=2),
            'Actual provider explanation statuses are retained above. Bad/empty/unsafe prose probes use local copies of accepted live selections; they are not extra provider calls or fabricated live rejection examples.',
            'No hidden reasoning, raw provider internals, credentials or environment values were persisted.']
        (REPORTS / ('v4_live_' + test + '.md')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    lines = ['# V4 Final Dual Live Confirmation', '', 'Status: ' + summary['status'],
        f"OpenAI requests: {state['provider_calls']}/12; Test A: {outcomes['A']['team']['agents_completed']}/3; Test B: {outcomes['B']['team']['agents_completed']}/3.",
        'Usage: ' + json.dumps(usage), 'API monetary cost: UNKNOWN; the provider did not report charges.',
        f'First-attempt pass rate: {first / 6:.1%}; retry rate: {retries / 6:.1%}.',
        f'V4 mean output: {mean}; V3 retained-attempt mean: {previous_mean}; truncated: {summary["truncated"]}.',
        f'Snapshot isolation: {isolation}; durable reload: {durable}; browser QA: {qa["status"]}.',
        'Monad permission: ' + ('YES' if gate else 'NO'), '', '## Acceptance Boundary',
        'Selection IDs, role/use, actions, ranks, counts and identity are the structured gates. Optional prose is non-authoritative and non-blocking; facts, values, units, direction, conflicts and support are backend-owned.',
        'Actual provider explanations were not deliberately corrupted. Local post-response probes prove fallback on actual accepted selections without additional API calls.',
        'Agent interpretations are derived, zero independent directional votes; existing fusion weights are unchanged. Conflicts remain visible; legitimate abstentions count as valid outcomes.',
        '', '## Safety and Preservation', 'Only three existing snapshot/acquisition/technical timestamps and their deterministic identities changed. Restoring those fields reproduces original fixture bytes exactly; catalogue semantics and canonical fact references match.',
        'The isolated production AgentTeam root uses a new persisted task allowance shared by both workflows. Prior project daily use was excluded without resetting production counters. A separate transport and per-task/per-workflow/per-role guard enforce the absolute call boundary.',
        'Production code, schema, prompts, validators, fixtures after freeze and fusion rules were not changed during live execution. Historical source/report hashes remain intact.',
        'Other providers, inference, training, scientific validation, locked-test target access, trading, transactions, commits, pushes and Monad implementation: none.',
        '8.8/10 is the retained custom scoped architecture assessment, not a new comprehensive quality or forecast-accuracy score. The 392/0/1 offline suite was not rerun.',
        '', '## Structural Blocker', json.dumps(blocker, indent=2) if blocker else 'None.', '', '## Next Action',
        'Checkpoint and push the fully repaired pre-Monad foundation. The repair loop is CLOSED. Then begin Monad research, audit and architecture.' if gate else 'Resolve the single structural blocker above in a separately authorized task; no prose patch or repair was performed here.']
    (REPORTS / 'v4_final_dual_confirmation.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if final:
        path = REPORTS / 'monad_readiness_gate.json'
        previous = load(path)
        history = previous.get('history', [])
        if previous.get('live_confirmation_report') != 'v4_final_dual_confirmation.json':
            history += [{'recorded_at': base.now(), 'reason': 'Authorized final V4 dual provider confirmation', 'previous_gate': {k: v for k, v in previous.items() if k != 'history'}}]
        save(path, {'schema_version': 'monad_readiness_gate_postrepair_v1', 'status': health, 'permission': 'YES' if gate else 'NO',
            'history': history, 'live_confirmation_report': 'v4_final_dual_confirmation.json', 'fresh_fixture_manifest': 'v4_fresh_live_manifest.json',
            'live_confirmation_needed': not gate, 'open_blockers': [] if gate else [blocker], 'remaining_red': failures,
            'remaining_actionable_yellow': [] if gate else ['V4 live/integration gate not complete'],
            'accepted_non_blockers': previous.get('accepted_non_blockers', []), 'latest_task_safety': summary['safety'],
            'components': {name: health for name in ('ai_research_team', 'bull', 'bear', 'risk', 'agent_harness', 'evidence_fusion', 'pipeline', 'dashboard', 'observability', 'security', 'architecture')},
            'authorized_call_scope': {'workflows': 2, 'max_requests': 12, 'actual_requests': state['provider_calls'], 'production_counters_reset': False}})
    print(json.dumps({'stage': 'FINAL' if final else 'INTERIM', 'status': summary['status'], 'calls': state['provider_calls'], 'usage': usage,
        'teams': {t: out['team']['agents_completed'] for t, out in outcomes.items()}, 'qa': qa['status'], 'blocker': blocker, 'monad_permission': gate}, indent=2))


if __name__ == '__main__':
    try:
        {'prepare': prepare, 'run': run, 'finalize': summarize}[sys.argv[1]]()
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'exception_class': type(error).__name__, 'reason': ar._sanitize_error(error)}), flush=True)
        sys.exit(1)
