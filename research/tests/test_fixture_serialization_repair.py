"""Offline fixture, exact byte-boundary, grounding, and fusion regressions."""
from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from app import agent_research as ar
from app.evidence_snapshot import canonical_bytes, snapshot_id
from app.evidence_fusion import EvidenceFusionEngine
from research.tests.fixtures.dual_retest_fixtures import build_fixture
from research.tests.test_phase7_agents import typed_claim, structured_fact, valid_report, concise_report
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response


def wire(record):
    # Historical v2_1 frozen serializer. Native v3 tests use ar.serialize_agent_input.
    return canonical_bytes({'snapshot_id': record['snapshot_id'], 'evidence': record['evidence'],
        'evidence_catalog': ar.evidence_catalog(record['evidence'])})


def report_for(role, fixture):
    test = fixture['test']; record = fixture['record']
    report = concise_report(valid_report(role, record['snapshot_id']))
    if role != 'risk':
        reference = 'kronos.direction' if role == 'bull' else 'technicals.trend'
        report['argument'] = structured_fact('forecast_direction' if role == 'bull' else 'technical_trend',
            record['evidence']['kronos']['direction'] if role == 'bull' else record['evidence']['technicals']['trend'],
            'state', [reference], evidence_type='FORECAST' if role == 'bull' else 'TECHNICAL')
        report['supporting_evidence_ids'] = [reference] if role == 'bull' or test == 'B' else []
        report['contradicting_evidence_ids'] = [] if role == 'bull' or test == 'B' else [reference]
        if role == 'bear' and test == 'A': report['stance'] = 'NO_STRONG_CASE'
    else:
        report['missing_evidence'] = []
        report['risk_factors'] = []
        report['conflicts'] = [typed_claim('The upward forecast and bearish technical trend may indicate conflicting evidence.',
            ['kronos.direction', 'technicals.trend'], claim_type='RISK', support_type='MIXED',
            evidence_type='MULTI_SOURCE')] if test == 'B' else []
        report['model_risks'] = [structured_fact('forecast_final_price', record['evidence']['kronos']['forecast_final_close'],
            'price', ['kronos.forecast_final_close'])] if test == 'A' else []
        report['event_risks'] = [typed_claim('The unconfirmed discussion may limit event conviction.', ['news.article.1'],
            claim_type='RISK', support_type='DERIVED', evidence_type='NEWS')] if test == 'B' else []
        report['risk_level'] = 'HIGH' if test == 'B' else 'MODERATE'
        report['evidence_ids'] = sorted({ref for _, claim in ar._claim_entries(report, role) for ref in claim['evidence_ids']})
    return report


def mocked_team(fixture, root):
    record = fixture['record']; before = canonical_bytes(record)
    client = MockClient(lambda role: mock_response(role, record['snapshot_id'], report=report_for(role, fixture)))
    obj = LegacyAgentTeam(root / 'agents', client_factory=lambda: client)
    engine = EvidenceFusionEngine(root / 'fusion')
    missing = engine.fuse(record, agent_result=obj.result(record), pipeline=fixture['pipeline'])
    pre = obj.preflight(record); result = obj.run(record)
    restored = LegacyAgentTeam(root / 'agents', client_factory=lambda: (_ for _ in ()).throw(AssertionError('Cache only')))
    reloaded = restored.result(record)
    fused = engine.fuse(record, agent_result=reloaded, pipeline=fixture['pipeline'])
    hit = engine.fuse(record, agent_result=reloaded, pipeline=fixture['pipeline'])
    rows = [json.loads(p.read_text()) for p in (root / 'agents/runs').glob('*.json')]
    checks = {'team': result['agents_completed'] == 3 and len(client.calls) == 3,
        'durable_reload': reloaded['team_status'] == 'COMPLETE',
        'pipeline': restored.health(record)['rows'] == 3,
        'ledger': len(rows) == 3 and all(r['claim_validation']['status'] == 'PASS' and r['cache_status'] == 'STORED' for r in rows),
        'cache_invalidation': fused['result_hash'] != missing['result_hash'] and fused['cache_status'] == 'miss' and hit['cache_status'] == 'hit',
        'agents_in_fusion': all('AGENT_' + r.upper() not in fused['missing_evidence'] for r in ar.AGENTS),
        'lineage': all(item['lineage_ids'] for item in fused['evidence_items']),
        'primary_available': not any(e in fused['missing_evidence'] for e in ('KRONOS_FORECAST','TECHNICAL_INTELLIGENCE','NEWS_INTELLIGENCE','PIPELINE_HEALTH')),
        'conflicts': fixture['test'] != 'B' or bool(fused['conflicts']),
        'immutability': before == canonical_bytes(record)}
    return {'preflight': pre, 'result': result, 'checks': checks, 'fusion': fused,
        'mock_provider_attempts': len(client.calls), 'external_calls': 0}


class FixtureSerializationRepairTests(unittest.TestCase):
    def setUp(self):
        self.stamp = datetime.now(timezone.utc).isoformat()
        self.fixtures = {t: build_fixture(t, self.stamp) for t in ('A', 'B')}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'})
        env.start(); self.addCleanup(env.stop)

    def test_both_exact_production_preflights_with_headroom(self):
        for f in self.fixtures.values():
            obj = LegacyAgentTeam(self.root)
            pre = obj.preflight(f['record'])
            self.assertEqual(pre['input_bytes'], len(wire(f['record'])))
            self.assertLessEqual(pre['input_bytes'], 42000)
            self.assertEqual(obj.config.max_input_bytes, 48000)
            self.assertGreaterEqual(len(ar.evidence_catalog(f['record']['evidence'])), 60)

    def test_same_stamp_same_bytes_hash_and_portability(self):
        for t, f in self.fixtures.items():
            self.assertEqual(canonical_bytes(f), canonical_bytes(build_fixture(t, self.stamp)))
            self.assertEqual(snapshot_id(f['record']['evidence']), f['record']['snapshot_id'])
            text = canonical_bytes(f).decode()
            for bad in ('OneDrive', 'Bharat', 'sk-proj-', 'tvly-', 'OPENAI_API_KEY', 'Monad'):
                self.assertNotIn(bad, text)
        self.assertNotEqual(self.fixtures['A']['record']['snapshot_id'], self.fixtures['B']['record']['snapshot_id'])

    def test_realistic_count_and_all_required_families(self):
        for f in self.fixtures.values():
            e = f['record']['evidence']; cat = ar.evidence_catalog(e)
            self.assertEqual(len(e['news']['article_evidence']), 8)
            self.assertEqual(len(e['technicals']['values']), 12)
            self.assertEqual(len({a['summary'] for a in e['news']['article_evidence']}), 8)
            self.assertEqual({ar._evidence_family(k) for k in cat}, {'NEWS','TECHNICAL','FORECAST','MARKET_DATA','RESEARCH_VIEW','INSTRUMENT'})
            for a in e['news']['article_evidence']:
                self.assertTrue(a['sha256'] and a['published_at'] and a['provider'] == 'synthetic')

    def test_adversarial_stressors_remain_present(self):
        e = self.fixtures['B']['record']['evidence']
        self.assertEqual(e['kronos']['direction'], 'up'); self.assertEqual(e['technicals']['trend'], 'bearish')
        self.assertEqual(e['technicals']['regime'], 'HIGH_VOLATILITY')
        self.assertIn('neutral', {i['signal'] for i in e['technicals']['values']})
        self.assertEqual(e['news']['article_evidence'][0]['sentiment'], 'positive')
        self.assertEqual(e['news']['article_evidence'][1]['sentiment'], 'uncertain')
        self.assertLess(e['news']['article_evidence'][1]['relevance'], 0.3)
        self.assertTrue(e['news']['uncertainty']); self.assertFalse(e['research_view']['confidence']['calibrated'])

    def test_both_full_mock_teams_cache_ledger_fusion_and_pipeline(self):
        for t,f in self.fixtures.items():
            with self.subTest(test=t):
                outcome = mocked_team(f, self.root / t)
                self.assertTrue(all(outcome['checks'].values()), outcome['checks'])

    def check(self, claim, role='risk'):
        return ar._validate_claim(claim, role, 'offline.fixture', ar.evidence_catalog(self.fixtures['B']['record']['evidence']))

    def test_supported_direct_fact_and_unsupported_demand_fact(self):
        title = self.fixtures['B']['record']['evidence']['news']['article_evidence'][0]['title']
        self.check(structured_fact('news_title', title, 'text', ['news.article.0'], evidence_type='NEWS'))
        with self.assertRaises(ar.ClaimValidationError):
            self.check(typed_claim('Demand is strengthening.', ['news.article.1'],
                claim_type='FACT', support_type='DIRECT', evidence_type='NEWS'))

    def test_interpretation_must_not_masquerade_as_fact(self):
        c = typed_claim('The partnership may support a constructive interpretation.', ['news.article.0'], evidence_type='NEWS')
        self.check(c); c.update(claim_type='FACT', support_type='DIRECT')
        with self.assertRaises(ar.ClaimValidationError): self.check(c)

    def test_mixed_family_needs_explicit_multi_source(self):
        c = typed_claim('The upward forecast and bearish trend may indicate conflicting evidence.', ['kronos.direction', 'technicals.trend'])
        with self.assertRaises(ar.ClaimValidationError): self.check(c)
        c.update(evidence_type='MULTI_SOURCE', support_type='MIXED'); self.check(c)

    def test_claim_splitting_supported(self):
        self.check(typed_claim('The upward forecast may be uncertain.', ['kronos.direction'], claim_type='RISK', support_type='DERIVED'))
        self.check(typed_claim('The bearish trend may limit positive conviction.', ['technicals.trend'], claim_type='RISK', support_type='DERIVED', evidence_type='TECHNICAL'))

    def test_numerical_value_and_unit_grounding(self):
        self.check(structured_fact('rsi', 44, 'unitless', ['technicals.indicator.0'], evidence_type='TECHNICAL'))
        for text in ('RSI is 62.', 'RSI is 44%.'):
            with self.assertRaises(ar.NumericalGroundingError):
                self.check(typed_claim(text, ['technicals.indicator.0'], claim_type='NUMERICAL_FACT', support_type='DIRECT', evidence_type='TECHNICAL'))
        self.check(structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change']))

    def test_irrelevant_missing_and_nonexistent_references_rejected(self):
        for ids, family in (([], 'NEWS'), (['news.article.99'], 'NEWS'), (['technicals.trend'], 'NEWS')):
            with self.assertRaises(ar.ClaimValidationError):
                self.check(typed_claim('The evidence may be uncertain.', ids, evidence_type=family))

    def test_input_boundary_48000_eligible_48001_blocked_without_client(self):
        for size in (47999, 48000, 48001, 50000):
            record = copy.deepcopy(self.fixtures['A']['record'])
            record['evidence']['fixture_padding'] = ''
            record['snapshot_id'] = snapshot_id(record['evidence'])
            record['evidence']['fixture_padding'] = 'x' * (size - len(wire(record)))
            record['snapshot_id'] = snapshot_id(record['evidence'])
            self.assertEqual(len(wire(record)), size)
            obj = LegacyAgentTeam(self.root / str(size), client_factory=lambda: self.fail('No API'))
            if size <= 48000: self.assertEqual(obj.preflight(record)['input_bytes'], size)
            else:
                with self.assertRaises(ar.AgentError) as err: obj.preflight(record)
                self.assertEqual(err.exception.code, 'INPUT_LIMIT')

    def test_missing_news_does_not_become_neutral(self):
        f = copy.deepcopy(self.fixtures['B']); record = f['record']
        record['evidence']['news']['gold_sha256'] = None
        record['snapshot_id'] = snapshot_id(record['evidence'])
        fused = EvidenceFusionEngine(self.root).fuse(record, pipeline=f['pipeline'])
        self.assertIn('NEWS_INTELLIGENCE', fused['missing_evidence'])
        self.assertFalse(any(i['evidence_type']=='NEWS' for i in fused['evidence_items']))

    def test_stale_guard_and_new_snapshot_cache_identity(self):
        record = copy.deepcopy(self.fixtures['A']['record']); obj = LegacyAgentTeam(self.root)
        record['created_at'] = '2000-01-01T00:00:00+00:00'
        record['evidence']['market_data']['retrieved_at'] = record['created_at']
        record['snapshot_id'] = snapshot_id(record['evidence'])
        with self.assertRaises(ar.AgentError): obj.preflight(record)
        for r in ar.AGENTS:
            self.assertNotEqual(obj._key(self.fixtures['A']['record']['snapshot_id'], r), obj._key(self.fixtures['B']['record']['snapshot_id'], r))
