"""Offline production V4 workflows; all providers are explicit mocks."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import agent_research as ar, agent_output_v3 as v3, agent_output_v4 as v4
from app.evidence_snapshot import canonical_bytes, snapshot_id
from app.evidence_fusion import EvidenceFusionEngine
from research.tests.fixtures.dual_retest_fixtures import build_fixture

def selection_for(role, wire, explanation=None):
    cat = wire['catalogue']
    candidates = sorted(cat, key=lambda key: (not key.startswith('context.'), key != 'technicals.regime', key))
    entries = []
    for key in candidates:
        modes = cat[key]['role_compatibility'][role]
        if not modes: continue
        use = 'RISK' if role == 'risk' else 'SUPPORT' if 'SUPPORT' in modes else 'COUNTER' if 'COUNTER' in modes else 'RISK'
        entries.append({'evidence_id': key, 'priority': len(entries) + 1, 'use': use})
        if len(entries) == v4.LIMITS[role]: break
    return {'schema_version': v4.SCHEMA_VERSION, 'agent_type': role, 'snapshot_id': wire['snapshot_id'],
        'action': 'ABSTAIN' if not entries else 'FLAG_RISK' if role == 'risk' else 'PRESENT_CASE',
        'selected_evidence': entries, 'optional_explanation': explanation}

class Client:
    def __init__(self, transform=None): self.calls = []; self.responses = self; self.transform = transform
    def create(self, **request):
        self.calls.append(request)
        role = request['text']['format']['name'].split('_')[0]
        wire = json.loads(request['input'].split('\n', 1)[1])
        report = selection_for(role, wire)
        if self.transform: report = self.transform(role, report, len(self.calls))
        return SimpleNamespace(status='completed', output_text=report if isinstance(report, str) else json.dumps(report),
            output=[], usage=SimpleNamespace(input_tokens=70, output_tokens=130, total_tokens=200),
            id='resp_offline_v4', _request_id='req_offline_v4', model='gpt-5-mini')

def full_team(fixture, root, transform=None):
    record = fixture['record']; before = canonical_bytes(record)
    client = Client(transform); team = ar.AgentTeam(root/'agents', client_factory=lambda: client)
    engine = EvidenceFusionEngine(root/'fusion')
    old = engine.fuse(record, agent_result=team.result(record), pipeline=fixture['pipeline'])
    preflight = team.preflight(record); result = team.run(record)
    restored = ar.AgentTeam(team.root, client_factory=lambda: (_ for _ in ()).throw(AssertionError('No provider on reload')))
    cached = restored.result(record)
    fusion = engine.fuse(record, agent_result=cached, pipeline=fixture['pipeline'])
    hit = engine.fuse(record, agent_result=cached, pipeline=fixture['pipeline'])
    items = [e for e in fusion['evidence_items'] if e['evidence_type'].startswith('AGENT_')]
    rows = [json.loads(p.read_text()) for p in (team.root/'runs').glob('*.json')]
    attempts = [json.loads(p.read_text()) for p in (team.root/'attempts').glob('*.json')]
    checks = {'team': result['agents_completed'] == 3, 'durable': cached['team_status'] == 'COMPLETE',
        'cache': old['result_hash'] != fusion['result_hash'] and hit['cache_status'] == 'hit',
        'fusion': len(items) == 3 and all(e['role'] == 'DERIVED' and not e['contributes_to_direction'] for e in items),
        'lineage': all(e['provenance']['agent_run_id'] for e in items),
        'conflicts': fixture['test'] != 'B' or bool(fusion['conflicts']),
        'ledger': len(rows) == 3 and all(r['output_schema_version'] == v4.SCHEMA_VERSION and r['cache_status'] == 'STORED' for r in rows),
        'attempts': len(attempts) == 3 and all(r['structured_validation'] == 'PASS' for r in attempts),
        'pipeline': restored.health(record)['status'] == 'HEALTHY',
        'dashboard': all(e['presentation']['schema_version'] == v4.SCHEMA_VERSION for e in cached['agents'].values()),
        'immutability': canonical_bytes(record) == before}
    return {'checks': checks, 'team': result, 'cached_team': cached, 'fusion': fusion,
        'preflight': preflight, 'health': restored.health(record), 'calls': len(client.calls), 'external_calls': 0}

class V4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = build_fixture('B', datetime.now(timezone.utc).isoformat())
        self.record = self.fixture['record']; self.raw = ar.evidence_catalog(self.record['evidence'])
        self.wire = json.loads(v4.serialize(self.record, self.raw))
        self.report = selection_for('bull', self.wire)
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'})
        self.env.start(); self.addCleanup(self.env.stop)
    def validate(self, report=None):
        return v4.validate(self.report if report is None else report, 'bull', self.record['snapshot_id'], self.raw)
    def reject(self, modify, code):
        value = copy.deepcopy(self.report); modify(value)
        with self.assertRaises(v4.ContractError) as caught: self.validate(value)
        self.assertEqual(caught.exception.code, code)
    def test_bad_id(self): self.reject(lambda r: r['selected_evidence'][0].update(evidence_id='FAKE_EVIDENCE_99'), 'unknown_evidence_id')
    def test_wrong_role(self): self.reject(lambda r: r.update(agent_type='bear'), 'schema_identity')
    def test_forbidden_mode(self):
        self.reject(lambda r: r.update(selected_evidence=[{'evidence_id':'kronos.direction','priority':1,'use':'COUNTER'}]), 'role_admissibility')
    def test_duplicate(self): self.reject(lambda r: r.update(selected_evidence=[r['selected_evidence'][0], {**r['selected_evidence'][0], 'priority':2}]), 'duplicate_evidence')
    def test_limit(self): self.reject(lambda r: r.update(selected_evidence=r['selected_evidence']*4), 'selection_limit')
    def test_rank_order(self): self.reject(lambda r: r['selected_evidence'][0].update(priority=2), 'priority_order')
    def test_bool_rank(self): self.reject(lambda r: r['selected_evidence'][0].update(priority=True), 'priority_order')
    def test_missing_snapshot(self): self.reject(lambda r: r.update(snapshot_id='other'), 'schema_identity')
    def test_new_schema_required(self): self.reject(lambda r: r.update(schema_version=v3.SCHEMA_VERSION), 'schema_identity')
    def test_action_enum(self): self.reject(lambda r: r.update(action='TRADE'), 'action_enum')
    def test_empty_case(self): self.reject(lambda r: r.update(selected_evidence=[]), 'action_selection_mismatch')
    def test_fact_field_forbidden(self): self.reject(lambda r: r.update(price=105), 'schema_shape')
    def test_direction_field_forbidden(self): self.reject(lambda r: r.update(stance='MIXED'), 'schema_shape')
    def test_unit_field_forbidden(self): self.reject(lambda r: r['selected_evidence'][0].update(unit='percent'), 'selection_shape')
    def test_abstention(self):
        r = copy.deepcopy(self.report); r.update(action='ABSTAIN', selected_evidence=[])
        result = v4.build_result(self.validate(r), 'bull', self.record['snapshot_id'], self.raw)
        self.assertEqual(result['direction'], 'UNCERTAIN'); self.assertEqual(result['support_level'], 'INSUFFICIENT')
    def test_number_explanation_nonblocking(self):
        r = copy.deepcopy(self.report); r['optional_explanation'] = 'RSI is 63.2, with 15% upside.'
        checked = self.validate(r); self.assertEqual(checked['explanation_status'], 'REJECTED')
        self.assertIsNone(checked['optional_explanation'])
    def test_arbitrary_wording_nonblocking(self):
        for text in ('Technical momentum remains constructive.', 'The primary evidence conflicts.', 'Liquidity conditions increase execution risk.', 'MIXED', 'nonsense prose'):
            r = {**self.report, 'optional_explanation': text}; self.validate(r)
    def test_garbage_explanation_nonblocking(self):
        for value in ([], {}, False, 15, '', ' ', 'x'*10000, None):
            checked = self.validate({**self.report, 'optional_explanation': value})
            self.assertIsNone(checked['optional_explanation'])
    def test_html_explanation_nonblocking_and_discarded(self):
        checked = self.validate({**self.report, 'optional_explanation':'<script>bad()</script>'})
        self.assertEqual(checked['explanation_status'], 'REJECTED')
    def test_path_secret_explanation_discarded(self):
        for text in ('D:\\private\\file', 'sk-project-pretendsecret', '/home/private/key'):
            self.assertIsNone(self.validate({**self.report, 'optional_explanation': text})['optional_explanation'])
    def test_env_secret_discarded(self):
        with patch.dict(os.environ, {'CUSTOM_TOKEN':'private-secret-example'}):
            self.assertIsNone(self.validate({**self.report, 'optional_explanation':'private-secret-example'})['optional_explanation'])
    def test_backend_direction_not_prose(self):
        r = {**self.report, 'selected_evidence':[{'evidence_id':'kronos.direction','priority':1,'use':'SUPPORT'}], 'optional_explanation':'This is bearish.'}
        result = v4.build_result(self.validate(r),'bull',self.record['snapshot_id'],self.raw)
        self.assertEqual(result['direction'],'BULLISH'); self.assertFalse(result['conflict'])
    def test_backend_conflict(self):
        r = {**self.report, 'selected_evidence':[{'evidence_id':'kronos.direction','priority':1,'use':'SUPPORT'}, {'evidence_id':'technicals.trend','priority':2,'use':'COUNTER'}]}
        result = v4.build_result(self.validate(r),'bull',self.record['snapshot_id'],self.raw)
        self.assertEqual(result['direction'],'MIXED'); self.assertTrue(result['conflict'])
    def test_facts_exact_backend(self):
        r = {**self.report, 'selected_evidence':[{'evidence_id':'kronos.direction','priority':1,'use':'SUPPORT'}]}
        facts = v4.build_result(self.validate(r),'bull',self.record['snapshot_id'],self.raw)['resolved_facts']
        self.assertEqual(facts[0]['value'], 'up'); self.assertEqual(facts[0]['unit'], 'state')
    def test_fallback_backend_only(self):
        r = self.validate({**self.report, 'optional_explanation':'Price reaches 105.'})
        display = v4.presentation(r,self.raw)
        self.assertEqual(display['explanation_status'],'REJECTED'); self.assertEqual(display['explanation'],display['fallback_explanation'])
    def test_prose_never_enters_fusion(self):
        a = self.validate({**self.report,'optional_explanation':'Positive outlook.'})
        b = self.validate({**self.report,'optional_explanation':'Negative outlook.'})
        self.assertEqual(v4.fusion_report(a,self.raw),v4.fusion_report(b,self.raw))
    def test_no_raw_provider_text_in_input(self):
        wire = canonical_bytes(self.wire)
        self.assertNotIn(b'full_text',wire); self.assertNotIn(b'https://example.org',wire)
        self.assertNotIn(b'forecast_pct_change":1.2',wire)
    def test_deterministic_input(self): self.assertEqual(v4.serialize(self.record,self.raw),v4.serialize(copy.deepcopy(self.record),copy.deepcopy(self.raw)))
    def test_normal_full_team(self):
        with tempfile.TemporaryDirectory() as folder:
            result = full_team(build_fixture('A',datetime.now(timezone.utc).isoformat()),Path(folder))
            self.assertTrue(all(result['checks'].values()), result['checks'])
    def test_adversarial_full_team(self):
        with tempfile.TemporaryDirectory() as folder:
            result = full_team(self.fixture,Path(folder)); self.assertTrue(all(result['checks'].values()),result['checks'])
    def test_bad_explanation_team_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            def corrupt(role,r,count): return {**r,'optional_explanation':'RSI is 63.2.'}
            result = full_team(self.fixture,Path(folder),corrupt)
            self.assertTrue(all(result['checks'].values()),result['checks'])
            self.assertTrue(all(e['presentation']['explanation_status']=='REJECTED' for e in result['cached_team']['agents'].values()))
    def test_abstaining_team_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            def abstain(role,r,count): return {**r,'action':'ABSTAIN','selected_evidence':[]}
            result = full_team(self.fixture,Path(folder),abstain)
            self.assertEqual(result['cached_team']['team_status'],'COMPLETE')
            self.assertEqual(result['health']['status'],'HEALTHY')
            items=[e for e in result['fusion']['evidence_items'] if e['evidence_type'].startswith('AGENT_')]
            self.assertTrue(all(e['metadata']['action']=='ABSTAIN' and e['strength']==0 for e in items))
    def test_malformed_twice_true_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Client(lambda *args:'{bad'); team=ar.AgentTeam(Path(folder),client_factory=lambda:client)
            result=team.run(self.record); self.assertEqual(len(client.calls),6); self.assertEqual(result['agents_completed'],0)
            self.assertFalse(list((Path(folder)/'cache').glob('*.json')))
            self.assertEqual(team.result(self.record)['status'],'FAILED')
    def test_bad_id_then_retry(self):
        def first_bad(role,r,count):
            if count == 1: r['selected_evidence'][0]['evidence_id']='FAKE'
            return r
        with tempfile.TemporaryDirectory() as folder:
            client=Client(first_bad); result=ar.AgentTeam(Path(folder),client_factory=lambda:client).run(self.record)
            self.assertEqual(result['agents_completed'],3); self.assertEqual(len(client.calls),4)
    def test_v3_cache_cannot_satisfy_v4(self):
        team=ar.AgentTeam(Path('unused')); old=ar.AgentTeam(Path('unused'),contract_version=v3.SCHEMA_VERSION)
        self.assertNotEqual(team._key(self.record['snapshot_id'],'bull'),old._key(self.record['snapshot_id'],'bull'))
    def test_validator_version_cache_miss(self):
        team=ar.AgentTeam(Path('unused')); key=team._key(self.record['snapshot_id'],'bull')
        with patch.object(v4,'VALIDATOR_VERSION','other'): self.assertNotEqual(key,team._key(self.record['snapshot_id'],'bull'))
    def test_prompt_version_cache_miss(self):
        team=ar.AgentTeam(Path('unused')); key=team._key(self.record['snapshot_id'],'bull')
        with patch.dict(v4.PROMPT_VERSIONS,{'bull':'other'}): self.assertNotEqual(key,team._key(self.record['snapshot_id'],'bull'))
    def test_config_limits_and_tools(self):
        team=ar.AgentTeam(Path('unused')); request=team._request_args('bull',team._serialize_input(self.record))
        self.assertEqual(team.config.max_input_bytes,48000); self.assertEqual(request['max_output_tokens'],1600)
        self.assertEqual(request['tools'],[]); self.assertEqual(request['tool_choice'],'none'); self.assertEqual(ar.MAX_RETRIES,1)
    def test_strict_schema_preflight(self):
        ar._strict_schema_preflight(v4.schema('bull',self.wire['catalogue']))
    def test_stale_input_blocked(self):
        r=copy.deepcopy(self.record); r['created_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        with self.assertRaises(ar.AgentError): ar.AgentTeam(Path('unused')).preflight(r)
    def test_fail_quality_not_directional_support(self):
        raw=copy.deepcopy(self.raw); raw['market_data.quality']='FAIL'
        cat=v4.catalogue(raw); self.assertNotIn('SUPPORT',cat['kronos.direction']['role_compatibility']['bull'])
    def test_legacy_v3_behavior_retained(self):
        with self.assertRaises(v3.ContractError): v3._prose('RSI is 63.2.')
    def test_input_smaller_than_v3(self): self.assertLess(len(v4.serialize(self.record,self.raw)),len(ar.serialize_agent_input(self.record)))
    def test_exact_input_limit(self):
        for length in (48000,48001):
            class PaddedTeam(ar.AgentTeam):
                def _serialize_input(inner,record):
                    wire=super()._serialize_input(record)
                    return wire+b' '*(length-len(wire))
            team=PaddedTeam(Path('unused'))
            if length==48000: self.assertEqual(team.preflight(self.record)['input_bytes'],48000)
            else:
                with self.assertRaises(ar.AgentError) as caught: team.preflight(self.record)
                self.assertEqual(caught.exception.code,'INPUT_LIMIT')
    def test_missing_news_is_not_neutral(self):
        raw={k:v for k,v in self.raw.items() if not k.startswith('news.')}
        cat=v4.catalogue(raw)
        self.assertIn('context.missing_evidence',cat)
        self.assertIn('MISSING_NEWS',cat['context.missing_evidence']['risk_flags'])
    def test_no_admissible_bear_case_abstains(self):
        raw={'kronos.direction':'up'}
        r={'schema_version':v4.SCHEMA_VERSION,'agent_type':'bear','snapshot_id':'synthetic',
           'action':'ABSTAIN','selected_evidence':[],'optional_explanation':None}
        self.assertEqual(v4.validate(r,'bear','synthetic',raw)['action'],'ABSTAIN')
    def test_stale_news_can_only_qualify(self):
        raw=copy.deepcopy(self.raw)
        raw['news.article.0']['published_at']=(datetime.now(timezone.utc)-timedelta(days=20)).isoformat()
        item=v4.catalogue(raw)['news.article.0']
        self.assertEqual(item['freshness'],'STALE'); self.assertNotIn('SUPPORT',item['role_compatibility']['bull'])
    def test_news_conflict_reference_lineage(self):
        item=v4.catalogue(self.raw)['context.directional_conflict']
        self.assertIn('kronos.direction',item['lineage_ids']); self.assertIn('technicals.trend',item['lineage_ids'])
    def test_garbage_then_fallback_preserves_numbers(self):
        r={**self.report,'selected_evidence':[{'evidence_id':'kronos.forecast_final_close','priority':1,'use':'RISK'}], 'optional_explanation':'Target 999.'}
        result=v4.build_result(self.validate(r),'bull',self.record['snapshot_id'],self.raw)
        self.assertEqual(result['resolved_facts'][0]['value'],101.2)
        self.assertNotIn('999',json.dumps(result))
    def test_ledger_failure_no_success_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            team=ar.AgentTeam(Path(folder),client_factory=Client)
            with patch.object(team,'_ledger',side_effect=OSError('offline persistence failure')):
                with self.assertRaises(ar.AgentError): team.run(self.record)
            self.assertFalse(list((Path(folder)/'cache').glob('*.json')))
    def test_cache_failure_does_not_publish(self):
        real=ar._atomic_json
        def failed_cache(path,value):
            if path.parent.name=='cache': raise OSError('offline cache failure')
            real(path,value)
        with tempfile.TemporaryDirectory() as folder,patch.object(ar,'_atomic_json',side_effect=failed_cache):
            team=ar.AgentTeam(Path(folder),client_factory=Client); result=team.run(self.record)
            self.assertEqual(result['agents_completed'],0); self.assertEqual(team.result(self.record)['team_status'],'FAILED')
    def test_durable_state_is_contract_specific(self):
        old=ar.AgentTeam(Path('unused'),contract_version=v3.SCHEMA_VERSION); current=ar.AgentTeam(Path('unused'))
        self.assertNotEqual(old._team_path(self.record['snapshot_id']),current._team_path(self.record['snapshot_id']))
    def test_unexpected_fusion_fields_rejected(self):
        with self.assertRaises(v4.ContractError): v4.build_result({**self.report,'fact':'fake'},'bull',self.record['snapshot_id'],self.raw)
    def test_rank_choice_is_not_semantically_judged(self):
        r={**self.report,'selected_evidence':list(reversed(self.report['selected_evidence']))}
        for i,e in enumerate(r['selected_evidence']): e['priority']=i+1
        self.validate(r)
    def test_counter_only_is_valid_but_no_role_support(self):
        r={**self.report,'selected_evidence':[{'evidence_id':'technicals.trend','priority':1,'use':'COUNTER'}]}
        result=v4.build_result(self.validate(r),'bull',self.record['snapshot_id'],self.raw)
        self.assertEqual(result['support_level'],'INSUFFICIENT')
        self.assertIn('NO_ROLE_ALIGNED_SUPPORT',result['uncertainty_flags'])
    def test_unknown_role_action_rejected(self): self.reject(lambda r:r.update(action='FLAG_RISK'),'action_enum')
    def test_unsafe_prose_not_stored_in_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            full_team(self.fixture,Path(folder),lambda role,r,n:{**r,'optional_explanation':'D:\\private\\secret sk-pretendapikey'})
            files=list(Path(folder).rglob('*.json'))
            contents=''.join(p.read_text() for p in files)
            self.assertNotIn('pretendapikey',contents); self.assertNotIn('private\\\\secret',contents)
