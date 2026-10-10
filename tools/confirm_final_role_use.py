"""One authorized Bull-only confirmation on frozen visible evidence; maximum two POSTs."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import agent_research as ar, agent_output_v4 as v4
from app.evidence_snapshot import canonical_bytes, save_snapshot, snapshot_id
from app.evidence_fusion import EvidenceFusionEngine
from app.usage_budget import DailyUsageBudget
from tools import final_reliability_audit as audit
from tools.run_v3_live_confirmation import credential, private_check

OUT = audit.OUT
EXECUTION = OUT / 'live_execution.json'
MANIFEST = OUT / 'live_manifest.json'
CONFIG = ar.AgentConfig()


def now(): return datetime.now(timezone.utc).isoformat()


def sources():
    return {str(p.relative_to(ROOT)).replace('\\', '/'): audit.digest(p)
            for p in (ROOT/'app').glob('*.py')}


def prepare():
    assert not MANIFEST.exists() and not EXECUTION.exists(), 'Do not replace frozen confirmation state'
    assert audit.read(OUT/'offline_tests.json')['failed'] == 0
    original = audit.read(audit.WINDOW / f'evidence_snapshots/{audit.SNAPSHOT}.json')
    ar.AgentTeam._verify_snapshot(original)
    content = copy.deepcopy(original['evidence'])
    old_acquired = content['market_data']['retrieved_at']
    content['market_data']['retrieved_at'] = now()
    restored = copy.deepcopy(content); restored['market_data']['retrieved_at'] = old_acquired
    assert restored == original['evidence'], 'Material evidence changed'
    old_cat = v4.catalogue(ar.evidence_catalog(original['evidence']))
    new_cat = v4.catalogue(ar.evidence_catalog(content))
    assert old_cat == new_cat, 'Role, direction, freshness, conflict or uncertainty catalogue changed'
    record = save_snapshot(OUT/'snapshots', content)
    assert record['snapshot_id'] != original['snapshot_id']
    team = ar.AgentTeam(OUT/'agents')
    credential()
    preflight = team.preflight(record)
    wire = v4.serialize(record, ar.evidence_catalog(content))
    private_check(json.loads(wire))
    assert (CONFIG.max_input_bytes, CONFIG.max_output_tokens, ar.MAX_RETRIES) == (48000, 1600, 1)
    assert CONFIG.model == 'gpt-5-mini'
    assert preflight['validator_version'] == 'evidence_selection_validator_v2'
    assert preflight['output_budget']['daily_limit_enforced'] is False
    assert team.result(record)['agents_completed'] == 0
    audit.save(MANIFEST, {'purpose': 'Bull-only software reliability confirmation; not a forecast rerun',
        'created_at': now(), 'old_snapshot_id': original['snapshot_id'], 'snapshot_id': record['snapshot_id'],
        'snapshot_file': str((OUT/'snapshots'/f"{record['snapshot_id']}.json").relative_to(ROOT)).replace('\\','/'),
        'snapshot_file_sha256': audit.digest(OUT/'snapshots'/f"{record['snapshot_id']}.json"),
        'semantic_difference': 0, 'catalogue_difference': 0,
        'changed_fields': ['created_at', 'evidence.market_data.retrieved_at', 'snapshot_id'],
        'original_source_bar_timestamp': content['technicals']['as_of'],
        'freshness_copy_not_new_market_acquisition': True,
        'schema': v4.SCHEMA_VERSION, 'validator': v4.VALIDATOR_VERSION,
        'role_use_contract': v4.ROLE_USE_CONTRACT_VERSION, 'prompt_versions': v4.PROMPT_VERSIONS,
        'config': asdict(CONFIG), 'maximum_calls': 2, 'agents': ['bull'],
        'input_bytes': len(wire), 'input_sha256': hashlib.sha256(wire).hexdigest(),
        'preflight': preflight, 'initial_bull_cache_miss': True, 'source_hashes': sources()})
    print(json.dumps({'preflight': 'PASS', 'snapshot': record['snapshot_id'],
          'semantic_difference': 0, 'catalogue_difference': 0, 'bytes': len(wire), 'maximum_calls': 2}))


class BoundedTransport:
    def __init__(self):
        import httpx2 as httpx
        self.inner = httpx.HTTPTransport(retries=0)
        self.count = 0
    def handle_request(self, request):
        if (request.method, request.url.scheme, request.url.host, request.url.path) != (
                'POST', 'https', 'api.openai.com', '/v1/responses'):
            raise RuntimeError('Non-authorized transport request blocked')
        if self.count >= 2: raise RuntimeError('Two-call authorization exhausted')
        state = audit.read(EXECUTION)
        assert state['provider_calls'] <= 2 and state['transport_calls'] == self.count
        self.count += 1
        state['transport_calls'] = self.count
        audit.save(EXECUTION, state)
        return self.inner.handle_request(request)
    def close(self): self.inner.close()


class GuardResponses:
    def __init__(self, client): self.client = client
    def create(self, **request):
        manifest = audit.read(MANIFEST)
        assert sources() == manifest['source_hashes'], 'Production code changed after freeze'
        state = audit.read(EXECUTION)
        assert state['provider_calls'] < 2
        wire = request['input'].split('\n', 1)[1].encode('utf-8')
        assert hashlib.sha256(wire).hexdigest() == manifest['input_sha256']
        payload = json.loads(wire)
        assert request['text']['format']['schema'] == v4.schema('bull', payload['catalogue'], payload['snapshot_id'])
        assert request['instructions'] == v4.instructions('bull', manifest['prompt_versions']['bull'])
        assert request['model'] == CONFIG.model and request['max_output_tokens'] == 1600
        assert request['tools'] == [] and request['tool_choice'] == 'none' and not request['parallel_tool_calls']
        private_check(payload)
        state['provider_calls'] += 1; audit.save(EXECUTION, state)
        print(f"Authorized Bull attempt {state['provider_calls']}/2", flush=True)
        return self.client.responses.create(**request)


def run():
    import httpx2 as httpx
    from openai import OpenAI
    assert not EXECUTION.exists(), 'Confirmation already started: read saved state, never rerun'
    manifest = audit.read(MANIFEST)
    assert sources() == manifest['source_hashes'] and asdict(CONFIG) == manifest['config']
    path = ROOT/manifest['snapshot_file']
    assert audit.digest(path) == manifest['snapshot_file_sha256']
    record = audit.read(path)
    assert snapshot_id(record['evidence']) == manifest['snapshot_id']
    ar.assert_fresh_snapshot(record)
    credential()
    budget = DailyUsageBudget(ROOT/'outputs/final_real_world_challenge/agents/openai_usage.sqlite3')
    before_count = budget.totals('openai_agents')[0]
    audit.save(EXECUTION, {'provider_calls': 0, 'transport_calls': 0, 'maximum_calls': 2,
        'started_at': now(), 'daily_count_before': before_count, 'status': 'RUNNING'})
    transport = BoundedTransport()
    http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.openai.com/v1',
                    max_retries=0, timeout=CONFIG.timeout_seconds, http_client=http)
    guarded = type('GuardClient', (), {})(); guarded.responses = GuardResponses(client)
    team = ar.AgentTeam(OUT/'agents', config=CONFIG, client_factory=lambda: guarded)
    team._usage = budget
    engine = EvidenceFusionEngine(OUT/'fusion')
    before_fusion = engine.fuse(record, agent_result=team.result(record))
    try:
        result = team.run_bull_only(record)
        audit.save(OUT/'bull_live_result.json', result)
        restored = ar.AgentTeam(team.root, config=CONFIG,
                  client_factory=lambda: (_ for _ in ()).throw(AssertionError('No provider on retrieval')))
        cached = restored.result(record)
        fusion = engine.fuse(record, agent_result=cached)
        bull = cached['agents']['bull']
        successful = bool(bull.get('report'))
        checks = {'structured_acceptance': successful,
            'durable_bull': successful and bull['status'] == 'CACHED',
            'snapshot_ownership': cached['snapshot_id'] == manifest['snapshot_id'],
            'fusion_refresh': successful and before_fusion['result_hash'] != fusion['result_hash'],
            'bull_in_fusion': successful and any(e['evidence_type'] == 'AGENT_BULL' for e in fusion['evidence_items']),
            'snapshot_immutable': audit.digest(path) == manifest['snapshot_file_sha256'],
            'production_immutable': sources() == manifest['source_hashes']}
        if successful:
            raw = ar.evidence_catalog(record['evidence'])
            backend = v4.build_result(bull['report'], 'bull', record['snapshot_id'], raw)
            checks['role_use'] = all(e['use'] in e['role_compatibility']['bull'] for e in backend['selected_evidence'])
            checks['backend_direction'] = backend['direction'] in {'BEARISH', 'UNCERTAIN', 'NEUTRAL'}
            checks['dashboard_adapter'] = bull['presentation']['schema_version'] == v4.SCHEMA_VERSION
            audit.save(OUT/'bull_backend_result.json', backend)
        checks['no_extra_roles'] = cached['agents_completed'] == (1 if successful else 0)
        audit.save(OUT/'bull_live_integration.json', {'checks': checks, 'cached_team': cached, 'fusion': fusion,
            'team_scope': 'Bull-only confirmation; Bear/Risk deliberately NOT_RUN; PARTIAL team is expected',
            'all_checks': all(checks.values())})
        state = audit.read(EXECUTION)
        state.update(status='PASS' if all(checks.values()) else 'FAIL', finished_at=now(),
            api_calls=result['api_calls'], daily_count_after=budget.totals('openai_agents')[0])
        audit.save(EXECUTION, state)
        print(json.dumps({'status': state['status'], 'calls': state['provider_calls'],
              'transport_calls': state['transport_calls'], 'checks': checks}))
    finally:
        client.close()
        state = audit.read(EXECUTION)
        if state['status'] == 'RUNNING':
            state.update(status='INTERRUPTED_OR_ERROR', finished_at=now())
            audit.save(EXECUTION, state)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']: prepare()
    elif sys.argv[1:] == ['run']: run()
    else: raise SystemExit('Choose prepare or run; neither action is repeatable')
