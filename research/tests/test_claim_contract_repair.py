"""Offline replay of real sanitized rejection shapes, with strict validators unchanged."""
from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import agent_research as ar
from app.evidence_fusion import EvidenceFusionEngine
from app.evidence_snapshot import canonical_bytes
from research.tests.test_health_remediation import production_record
from research.tests.test_phase7_agents import typed_claim, structured_fact, concise_report, valid_report, snapshot
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response

OLD_PROMPTS={"bull":"bull_agent_prompt_v6","bear":"bear_agent_prompt_v5","risk":"risk_agent_prompt_v5"}
CASES=json.loads((Path(__file__).parent/'fixtures/claim_contract_live_rejections.json').read_text(encoding='utf-8'))['cases']

def replay_claim(case, *, corrected=False):
    return typed_claim(case['corrected_text'] if corrected else case['text'],case['evidence_ids'],
        claim_type='INTERPRETATION' if corrected else case['claim_type'],
        support_type='MIXED' if corrected and case['agent']=='risk' else 'INTERPRETIVE' if corrected else case['support_type'],
        evidence_type='MULTI_SOURCE' if corrected and case['agent']=='risk' else case['evidence_type'])

def repaired_report(role, digest):
    report=concise_report(valid_report(role,digest))
    if role!='risk':
        report['argument']=typed_claim(
            'The bullish technical trend may support a constructive case.' if role=='bull' else
            'The bullish technical trend may limit the downside case.', ['technicals.trend'], evidence_type='TECHNICAL')
        report['supporting_evidence_ids']=['technicals.trend'] if role=='bull' else []
        report['contradicting_evidence_ids']=[] if role=='bull' else ['technicals.trend']
        if role=='bear': report['stance']='NO_STRONG_CASE'
    else:
        report['missing_evidence']=[]
        report['model_risks']=[typed_claim('The upward forecast may be uncertain.', ['kronos.direction'],
                                        claim_type='RISK', support_type='DERIVED')]
        report['evidence_ids']=sorted({ref for _,claim in ar._claim_entries(report,role) for ref in claim['evidence_ids']})
    return report

class ClaimContractRepairTests(unittest.TestCase):
    def setUp(self):
        self.record=production_record()
        self.catalog=ar.evidence_catalog(self.record['evidence'])
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'})
        env.start(); self.addCleanup(env.stop)

    def check(self, claim, role='bull', catalog=None):
        return ar._validate_claim(claim,role,'offline.replay',catalog or self.catalog)

    def test_all_six_original_failures_remain_rejected(self):
        for case in CASES:
            with self.subTest(agent=case['agent'],attempt=case['attempt']):
                with self.assertRaises(ar.ClaimValidationError) as error:
                    self.check(replay_claim(case),case['agent'])
                diagnostic=error.exception.diagnostic
                self.assertEqual(diagnostic['failure_reason'],case['reason'])
                self.assertEqual(diagnostic['actual_evidence_families'],sorted({ar._evidence_family(x) for x in case['evidence_ids']}))
                self.assertEqual(diagnostic['claim_type'],case['claim_type'])
                self.assertEqual(diagnostic['support_type'],case['support_type'])

    def test_all_six_explicit_interpretations_pass_without_auto_rewriting(self):
        for case in CASES:
            with self.subTest(agent=case['agent'],attempt=case['attempt']):
                claim=replay_claim(case,corrected=True)
                self.assertEqual(self.check(claim,case['agent']),claim)

    def test_direct_supported_and_unsupported_fact_symmetric(self):
        for role in ar.AGENTS:
            with self.subTest(role=role):
                claim=structured_fact('forecast_direction','up','state',['kronos.direction'])
                self.check(claim,role)
                claim['text']='Demand is strengthening.'
                with self.assertRaises(ar.ClaimValidationError): self.check(claim,role)

    def test_supported_technical_interpretation_and_mislabeled_fact(self):
        for role in ar.AGENTS:
            claim=typed_claim('The technical indicators suggest positive momentum.',['technicals.indicator.0'],evidence_type='TECHNICAL',support_type='DERIVED')
            self.check(claim,role)
            claim.update(claim_type='FACT',support_type='DIRECT')
            with self.assertRaises(ar.ClaimValidationError): self.check(claim,role)

    def test_mixed_forecast_news_needs_explicit_multi_source(self):
        claim=typed_claim('The forecast and neutral news may indicate uncertainty.',['kronos.direction','news.article.0'])
        with self.assertRaises(ar.ClaimValidationError): self.check(claim,'risk')
        claim.update(evidence_type='MULTI_SOURCE',support_type='MIXED')
        self.check(claim,'risk')

    def test_risk_observations_split_by_family(self):
        for claim in [typed_claim('The forecast may be uncertain.',['kronos.direction'],claim_type='RISK',support_type='DERIVED'),
                      typed_claim('The neutral news may limit event conviction.',['news.article.0'],claim_type='RISK',support_type='DERIVED',evidence_type='NEWS')]:
            self.check(claim,'risk')

    def test_numbers_in_interpretations_remain_field_unit_and_value_supported(self):
        for role in ar.AGENTS:
            claim=typed_claim('RSI is 55 and may suggest positive momentum.',['technicals.indicator.0'],evidence_type='TECHNICAL')
            self.check(claim,role)
            for text in ('RSI is 62 and may suggest positive momentum.','RSI is 55% and may suggest positive momentum.'):
                claim['text']=text
                with self.assertRaises(ar.NumericalGroundingError): self.check(claim,role)

    def test_wrong_family_nonexistent_source_and_missing_ids(self):
        for role in ar.AGENTS:
            for ids,family in [(['technicals.trend'],'NEWS'),(['news.article.999'],'NEWS'),([],'TECHNICAL')]:
                claim=typed_claim('The evidence may support an interpretation.',ids,evidence_type=family)
                with self.subTest(role=role,ids=ids), self.assertRaises(ar.ClaimValidationError): self.check(claim,role)

    def test_many_ids_same_family_are_not_multi_source(self):
        claim=typed_claim('The bullish signals may support constructive momentum.',['technicals.indicator.0','technicals.indicator.1'],evidence_type='TECHNICAL')
        self.check(claim)
        claim['evidence_type']='MULTI_SOURCE'
        with self.assertRaises(ar.ClaimValidationError): self.check(claim)

    def test_actual_conflict_preserves_both_sources(self):
        claim=typed_claim('The forecast and research view may indicate conflicting evidence.',['kronos.direction','research_view.why'],support_type='MIXED',evidence_type='MULTI_SOURCE')
        self.check(claim,'risk')
        self.assertEqual(len({ar._evidence_family(x) for x in claim['evidence_ids']}),2)

    def test_missing_evidence_cites_explicit_availability_state(self):
        content=copy.deepcopy(self.record['evidence'])
        content['news'].update(evidence_status='NO_EVIDENCE',article_evidence=[])
        catalog=ar.evidence_catalog(content)
        claim=typed_claim('The no-evidence news state may limit event interpretation.',['news.evidence_status'],claim_type='UNCERTAINTY',support_type='DERIVED',evidence_type='NEWS')
        self.check(claim,'risk',catalog)
        claim['evidence_ids']=['news.article.0']
        with self.assertRaises(ar.ClaimValidationError): self.check(claim,'risk',catalog)

    def test_impossible_support_type_combinations_remain_rejected(self):
        cases=[('FACT','DERIVED','up'),('NUMERICAL_FACT','DERIVED','Forecast change is 1.2%.'),
               ('INTERPRETATION','DIRECT','The forecast may support the case.'),
               ('COMPARATIVE','DIRECT','The forecast may support the case.'),
               ('INTERPRETATION','INSUFFICIENT','The forecast may support the case.')]
        for role in ar.AGENTS:
            for kind,support,text in cases:
                with self.subTest(role=role,kind=kind,support=support), self.assertRaises(ar.ClaimValidationError):
                    self.check(typed_claim(text,['kronos.direction'],claim_type=kind,support_type=support),role)

    def test_shared_prompt_family_map_and_versions(self):
        self.assertEqual(ar.LEGACY_PROMPT_VERSIONS,{'bull':'bull_agent_prompt_v9','bear':'bear_agent_prompt_v8','risk':'risk_agent_prompt_v8'})
        shared=ar.claim_contract_instructions()
        for role in ar.AGENTS:
            text=ar.legacy_instructions(role)
            self.assertIn(shared,text)
            for prefix,family in ar.EVIDENCE_FAMILY_PREFIXES.items():
                self.assertEqual(ar._evidence_family(prefix+'.field'),family)
                self.assertIn(prefix+'.*='+family,text)
            for marker in ('FACT/DIRECT','INTERPRETATION/DERIVED','MULTI_SOURCE','Prefer one material claim per evidence family','Missing evidence must cite'):
                self.assertIn(marker,text)
        self.assertEqual(ar.EVIDENCE_TYPES,('NEWS','TECHNICAL','FORECAST','MARKET_DATA','RESEARCH_VIEW','INSTRUMENT','MULTI_SOURCE','NONE'))

    def test_mocked_production_sized_team_ledger_cache_fusion_and_reload(self):
        before=canonical_bytes(self.record)
        client=MockClient(lambda role: mock_response(role,self.record['snapshot_id'],report=repaired_report(role,self.record['snapshot_id'])))
        team=LegacyAgentTeam(self.root/'agents',client_factory=lambda:client)
        pre=team.preflight(self.record)
        self.assertGreater(pre['input_bytes'],30000)
        self.assertLessEqual(pre['input_bytes'],48000)
        engine=EvidenceFusionEngine(self.root/'fusion')
        missing=engine.fuse(self.record,agent_result=team.result(self.record))
        result=team.run(self.record)
        self.assertEqual(result['team_status'],'COMPLETE')
        self.assertEqual(result['agents_completed'],3)
        self.assertEqual(len(client.calls),3)
        self.assertTrue(all(c['tools']==[] and c['max_output_tokens']==1600 for c in client.calls))
        restored=LegacyAgentTeam(team.root,client_factory=lambda:self.fail('Cache only'))
        self.assertEqual(restored.result(self.record)['team_status'],'COMPLETE')
        self.assertEqual(restored.health(self.record)['rows'],3)
        fused=engine.fuse(self.record,agent_result=restored.result(self.record))
        self.assertNotEqual(missing['result_hash'],fused['result_hash'])
        for category in ('AGENT_BULL','AGENT_BEAR','AGENT_RISK'): self.assertNotIn(category,fused['missing_evidence'])
        self.assertEqual(canonical_bytes(self.record),before)
        for file in (team.root/'runs').glob('*.json'):
            row=json.loads(file.read_text())
            self.assertEqual(row['claim_validation']['status'],'PASS')
            self.assertEqual(row['cache_status'],'STORED')
            self.assertTrue(row['claim_metadata'])

    def test_old_prompt_success_cache_is_not_reused(self):
        client=MockClient(lambda role: mock_response(role,self.record['snapshot_id'],report=repaired_report(role,self.record['snapshot_id'])))
        team=LegacyAgentTeam(self.root,client_factory=lambda:client)
        with patch.dict(ar.LEGACY_PROMPT_VERSIONS,OLD_PROMPTS):
            old_keys={role:team._key(self.record['snapshot_id'],role) for role in ar.AGENTS}
            self.assertEqual(team.run(self.record)['agents_completed'],3)
        for role in ar.AGENTS:
            self.assertNotEqual(old_keys[role],team._key(self.record['snapshot_id'],role))
            self.assertIsNone(team._cached(self.record['snapshot_id'],role,self.catalog))
        self.assertEqual(LegacyAgentTeam(self.root).result(self.record)['agents_completed'],0)

    def test_rejected_claim_diagnostics_survive_retry_and_ledger_without_cache(self):
        original=CASES[0]
        report=repaired_report('bull',self.record['snapshot_id'])
        report['argument']=replay_claim(original)
        client=MockClient(lambda role: mock_response(role,self.record['snapshot_id'],report=report))
        team=LegacyAgentTeam(self.root,client_factory=lambda:client)
        self.assertEqual(team.run_bull_only(self.record)['status'],'FAILED')
        self.assertEqual(len(client.calls),2)
        self.assertEqual(list((self.root/'cache').glob('*.json')),[])
        rows=[json.loads(p.read_text()) for p in (self.root/'attempts').glob('*.json')]
        self.assertTrue(all(r['validation_diagnostic']['actual_evidence_families']==['TECHNICAL'] for r in rows))
        self.assertTrue(all(r['failure_stage']=='CLAIM_VALIDATION' for r in rows))
        parent=json.loads(next((self.root/'runs').glob('*.json')).read_text())
        self.assertEqual(len(parent['validation_diagnostic_attempt_refs']),2)
