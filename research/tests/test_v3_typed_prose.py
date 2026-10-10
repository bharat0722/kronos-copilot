"""Offline typed-prose regression and safe, located rejection diagnostics."""
from __future__ import annotations
import copy
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import agent_research as ar, agent_output_v3 as v3
from research.tests.legacy_agent_harness import LegacyV3AgentTeam
from app.evidence_fusion import EvidenceFusionEngine
from app.evidence_snapshot import canonical_bytes
from research.tests.fixtures.dual_retest_fixtures import build_fixture
from research.tests.test_agent_output_v3 import NativeClient, report_for, response

OLD_HEDGE = re.compile(r'\b(?:may|might|could|appears|suggests|uncertain|uncertainty|limited|conflict|caution|risk|unvalidated|uncalibrated)\b', re.I)

def unhedged_report(role, report):
    for argument in report['arguments']:
        families = {ref.split('.')[0] for ref in argument['interpretation']['evidence_ids']}
        subject = 'The forecast and technical evidence' if len(families)>1 else {
            'kronos':'The forecast evidence', 'technicals':'The technical evidence',
            'news':'The news evidence', 'research_view':'The research context',
            'market_data':'The market data'}.get(next(iter(families)), 'The cited evidence')
        suffix = ('conflict.' if argument['stance']=='MIXED' else
            'supports a constructive interpretation.' if role=='bull' else
            'supports a bearish interpretation.' if role=='bear' and argument['stance']=='BEARISH' else
            'does not establish a clear directional case.' if role=='bear' else
            'does not establish dependable outcomes.')
        argument['interpretation']['text'] = subject + ' ' + suffix
    report['limitations'][0]['text'] = 'The forecast has not been calibrated.'
    report['uncertainty'][0]['text'] = 'Outcomes remain unresolved.'
    return report

def typed_report(role, record):
    return unhedged_report(role, report_for(role, record))

def typed_response(role, report, call):
    # Modify only mock presentation prose; provider execution is always mocked.
    return response(unhedged_report(role, report))

def typed_team(fixture, root):
    record=fixture['record']; before=canonical_bytes(fixture)
    client=NativeClient(typed_response); team=LegacyV3AgentTeam(root/'agents',client_factory=lambda:client)
    preflight=team.preflight(record); engine=EvidenceFusionEngine(root/'fusion')
    pre=engine.fuse(record,agent_result=team.result(record),pipeline=fixture['pipeline'])
    result=team.run(record)
    restored=LegacyV3AgentTeam(team.root,client_factory=lambda: (_ for _ in ()).throw(AssertionError('No network on reload')))
    cached=restored.result(record); fused=engine.fuse(record,agent_result=cached,pipeline=fixture['pipeline'])
    hit=engine.fuse(record,agent_result=cached,pipeline=fixture['pipeline'])
    ledger=[json.loads(p.read_text()) for p in (team.root/'runs').glob('*.json')]
    attempts=[json.loads(p.read_text()) for p in (team.root/'attempts').glob('*.json')]
    items=[i for i in fused['evidence_items'] if i['evidence_type'].startswith('AGENT_')]
    checks={'team':result['agents_completed']==3 and len(client.calls)==3,
        'durable':cached['team_status']=='COMPLETE','cache':hit['cache_status']=='hit' and fused['result_hash']!=pre['result_hash'],
        'ledger':len(ledger)==3 and all(row['status']=='SUCCESS' and row['cache_status']=='STORED' for row in ledger),
        'attempts':len(attempts)==3 and all(row['status']=='SUCCESS' for row in attempts),
        'fusion':len(items)==3 and all(i['role']=='DERIVED' and not i['contributes_to_direction'] for i in items),
        'lineage':all(i['lineage_ids'] and i['provenance']['agent_run_id'] for i in items),
        'conflicts':fixture['test']!='B' or bool(fused['conflicts']),
        'dashboard_adapter':all(e['presentation']['arguments'] and e['presentation']['arguments'][0]['facts'] for e in cached['agents'].values()),
        'pipeline':restored.health(record)['status']=='HEALTHY','immutability':before==canonical_bytes(fixture)}
    return {'checks':checks,'preflight':preflight,'team':result,'cached_team':cached,'fusion':fused,'health':restored.health(record),'pipeline':fixture['pipeline'],'attempts':attempts,'ledger':ledger,'external_calls':0}

class TypedProseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=build_fixture('B',datetime.now(timezone.utc).isoformat());self.record=self.fixture['record']
        self.catalog=ar.evidence_catalog(self.record['evidence']);self.report=typed_report('bull',self.record)
    def validate(self,report=None):
        return ar.validate_current_output(report or self.report,'bull',self.record['snapshot_id'],self.catalog)
    def rejected(self,mutate):
        report=copy.deepcopy(self.report);mutate(report)
        with self.assertRaises((ar.ClaimValidationError,ar.NumericalGroundingError,ar.SchemaValidationError)) as caught:self.validate(report)
        self.assertTrue(caught.exception.diagnostic['json_path'].startswith('$'))
        self.assertTrue(caught.exception.diagnostic['rule_code'])
        return caught.exception.diagnostic
    def test_unhedged_typed_interpretations(self):
        for text in ('Technical momentum remains constructive.','Technical evidence is mixed.','The forecast and technical evidence conflict.',
                     'Liquidity conditions increase execution risk.','The available evidence supports a bearish interpretation.'):
            with self.subTest(text=text):
                # Classification accepts these phrases; full-output tests separately bind stance and evidence.
                v3._prose(text, '$.arguments[0].interpretation.text')
        self.validate()
    def test_with_hedge_remains_valid(self):
        self.report['arguments'][0]['interpretation']['text']='Technical momentum appears constructive.';self.validate()
    def test_note_typing_without_hedge(self):self.validate()
    def test_old_keyword_failure_structural_equivalent(self):
        text='Technical momentum remains constructive.';self.assertIsNone(OLD_HEDGE.search(text))
        self.report['arguments'][0]['interpretation']['text']=text;self.validate()
    def test_numeric_prose_still_rejected(self):
        for text in ('RSI is 63.2.','The forecast is +2.4%.','Price should reach 105.','The setup improves by ten percent.'):
            with self.subTest(text=text):
                d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text=text))
                self.assertEqual(d['rule_code'],'model_generated_number')
    def test_direct_fact_still_rejected(self):
        for text in ('Demand is strengthening.','The company announced a deal.','Forecast direction is bullish.'):
            with self.subTest(text=text):self.assertEqual(self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text=text))['rule_code'],'deterministic_fact_in_prose')
    def test_fact_type_rejected(self):
        d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(claim_type='FACT'))
        self.assertEqual(d['json_path'],'$.arguments[0].interpretation.claim_type');self.assertEqual(d['claim_type'],'FACT')
    def test_bad_support_type(self):self.rejected(lambda r:r['arguments'][0]['interpretation'].update(support_type='DIRECT'))
    def test_unknown_evidence(self):self.rejected(lambda r:r['arguments'][0]['interpretation'].update(evidence_ids=['unknown.id']))
    def test_no_evidence(self):self.rejected(lambda r:r['arguments'][0]['interpretation'].update(evidence_ids=[]))
    def test_irrelevant_family(self):
        d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(evidence_ids=['instrument.canonical_symbol']))
        self.assertEqual(d['rule_code'],'irrelevant_evidence_family')
    def test_cross_family_conflict(self):
        report=typed_report('risk',self.record)
        ar.validate_current_output(report,'risk',self.record['snapshot_id'],self.catalog)
        self.assertEqual(len(report['arguments'][1]['interpretation']['evidence_ids']),2)
    def test_role_stance_unknown(self):self.rejected(lambda r:r['arguments'][0].update(stance='BEARISH'))
    def test_bull_bearish_only_evidence(self):
        def mutate(r):
            a=r['arguments'][0];a['interpretation']['evidence_ids']=['technicals.trend'];a['evidence_fact_refs']=[{'evidence_id':'technicals.trend','field_key':'technical_trend'}]
        self.assertEqual(self.rejected(mutate)['rule_code'],'unsupported_directional_stance')
    def test_overlong(self):self.assertEqual(self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text='x'*241))['rule_code'],'schema_string')
    def test_empty(self):self.assertEqual(self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text=' '))['rule_code'],'empty_interpretation')
    def test_malformed(self):self.rejected(lambda r:r['arguments'][0].update(interpretation=[]))
    def test_schema_escape(self):self.rejected(lambda r:r['arguments'][0]['interpretation'].update(value=99))
    def test_second_argument_location(self):
        d=self.rejected(lambda r:r['arguments'][1]['interpretation'].update(text='RSI is 63.2.'))
        self.assertEqual(d['json_path'],'$.arguments[1].interpretation.text');self.assertEqual(d['argument_id'],'A2')
        self.assertEqual(d['evidence_families'],['NEWS']);self.assertEqual(d['text_excerpt'],'RSI is 63.2.')
    def test_limitation_location(self):
        self.assertEqual(self.rejected(lambda r:r['limitations'][0].update(text='Price is 100.'))['json_path'],'$.limitations[0].text')
    def test_uncertainty_location(self):
        self.assertEqual(self.rejected(lambda r:r['uncertainty'][0].update(text='The price is 99.'))['json_path'],'$.uncertainty[0].text')
    def test_snapshot_location(self):
        d=self.rejected(lambda r:r.update(snapshot_id='wrong'));self.assertEqual(d['json_path'],'$.snapshot_id')
    def test_missing_property_location(self):
        self.assertEqual(self.rejected(lambda r:r['arguments'][0]['interpretation'].pop('text'))['json_path'],'$.arguments[0].interpretation.text')
    def test_ref_binding_location(self):
        self.assertEqual(self.rejected(lambda r:r['arguments'][0]['evidence_fact_refs'][0].update(field_key='rsi'))['json_path'],'$.arguments[0].evidence_fact_refs[0]')
    def test_bounded_excerpt(self):
        d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text='text '*100))
        self.assertLessEqual(len(d['text_excerpt']),240)
    def test_secret_and_windows_path_redaction(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-secret-abcdef','CUSTOM_TOKEN':'custom-secret-xyz'}):
            text='synthetic-secret-abcdef custom-secret-xyz Bearer abcdefghi D:\\Private Folder\\file.txt'
            d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(text=text))
            wire=json.dumps(d);self.assertNotIn('synthetic-secret-abcdef',wire);self.assertNotIn('custom-secret-xyz',wire);self.assertNotIn('Private Folder',wire);self.assertNotIn('abcdefghi',wire)
    def test_sanitized_ids_and_argument_id(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-secret-abcdef'}):
            d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(evidence_ids=['synthetic-secret-abcdef']))
            self.assertNotIn('synthetic-secret-abcdef',json.dumps(d))
            d=self.rejected(lambda r:r['arguments'][0].update(argument_id='synthetic-secret-abcdef'))
            self.assertNotIn('synthetic-secret-abcdef',json.dumps(d))
            d=self.rejected(lambda r:r['arguments'][0]['interpretation'].update(claim_type='synthetic-secret-abcdef'))
            self.assertNotIn('synthetic-secret-abcdef',json.dumps(d))
    def test_unix_unc_and_private_key_excerpt(self):
        for text in ('Private /opt/research/project/file.txt', r'Private \\server\Private Folder\file.txt',
                     '-----BEGIN RSA PRIVATE KEY-----\nprivate material'):
            with self.subTest(text=text):
                excerpt=ar._safe_v3_excerpt(text)
                self.assertNotIn('file.txt',excerpt);self.assertNotIn('private material',excerpt)
                self.assertNotIn('Private Folder',excerpt)
    def test_non_string_root_no_raw_payload(self):
        with self.assertRaises(ar.SchemaValidationError) as caught:self.validate('private-root-payload')
        self.assertIsNone(caught.exception.diagnostic['text_excerpt'])
    def test_legacy_keyword_rule_unchanged(self):
        from research.tests.test_phase7_agents import evidence, snapshot, valid_report
        record = snapshot(evidence()); report = valid_report('bull', record['snapshot_id'])
        report['argument']['text'] = 'The evidence remains unresolved.'
        with self.assertRaises(ar.ClaimValidationError) as caught:
            ar.validate_output(report, 'bull', record['snapshot_id'], ar.evidence_catalog(record['evidence']))
        self.assertEqual(caught.exception.diagnostic['failure_reason'], 'unlabelled_interpretation')
    def test_cache_validator_version(self):
        team=LegacyV3AgentTeam(Path('unused-offline-cache'))
        current=team._key(self.record['snapshot_id'],'bull')
        with patch.object(v3,'VALIDATOR_VERSION','evidence_native_grounding_v1'):
            self.assertNotEqual(current,team._key(self.record['snapshot_id'],'bull'))
    def test_mock_ledger_precise_diagnostics(self):
        def invalid(role,report,call):
            report=typed_report(role,self.record)
            report['arguments'][0]['interpretation']['text']='RSI is 63.2.'
            return response(report)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'}):
            client=NativeClient(invalid);team=LegacyV3AgentTeam(Path(folder),client_factory=lambda:client);out=team.run(self.record)
            self.assertEqual(out['agents_completed'],0)
            for path in (Path(folder)/'attempts').glob('*.json'):
                row=json.loads(path.read_text());d=row['validation_diagnostic']
                self.assertEqual(d['run_id'],row['run_id']);self.assertEqual(d['attempt'],row['attempt']);self.assertEqual(d['prompt_version'],row['prompt_version'])
                self.assertEqual(d['json_path'],'$.arguments[0].interpretation.text');self.assertEqual(d['rule_code'],'model_generated_number')
    def test_mock_schema_failure_ledger(self):
        def invalid(role,report,call):report['snapshot_id']='wrong';return response(report)
        self.check_failed_ledger(invalid,'snapshot_identity','$.snapshot_id')
    def test_mock_invalid_json_ledger(self):
        def invalid(role,report,call):r=response(report);r.output_text='{bad';return r
        self.check_failed_ledger(invalid,'invalid_json','$')
    def check_failed_ledger(self,callback,code,path):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'}):
            client=NativeClient(callback);team=LegacyV3AgentTeam(Path(folder),client_factory=lambda:client);team.run(self.record)
            for file in (Path(folder)/'attempts').glob('*.json'):
                diagnostic=json.loads(file.read_text())['validation_diagnostic']
                self.assertEqual(diagnostic['rule_code'],code);self.assertEqual(diagnostic['json_path'],path)
    def test_normal_full_team(self):self.check_team('A')
    def test_adversarial_full_team(self):self.check_team('B')
    def check_team(self,test):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'}):
            outcome=typed_team(build_fixture(test,datetime.now(timezone.utc).isoformat()),Path(folder))
            self.assertTrue(all(outcome['checks'].values()),outcome['checks'])

if __name__=='__main__':unittest.main()
