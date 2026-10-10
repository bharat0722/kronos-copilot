"""Role/use pairing and bounded execution regressions; never call a live provider."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import agent_research as ar, agent_output_v4 as v4
from research.tests.test_agent_output_v4 import Client, full_team
from research.tests.fixtures.dual_retest_fixtures import build_fixture

FIXTURE = Path(__file__).parent / 'fixtures/window2_role_use_regression.json'


def offered(schema, key, mode):
    items = schema['properties']['selected_evidence']['items']
    branches = items.get('anyOf', [])
    return any(key in b['properties']['evidence_id']['enum'] and mode in b['properties']['use']['enum']
               for b in branches)


class FinalRoleUseTests(unittest.TestCase):
    def setUp(self):
        self.replay = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.raw = self.replay['raw']
        self.report = self.replay['reconstruction']
        self.cat = v4.catalogue(self.raw)
        self.fixture = build_fixture('B', datetime.now(timezone.utc).isoformat())
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'})
        env.start(); self.addCleanup(env.stop)

    def check(self, role, direction, mode, valid):
        raw = copy.deepcopy(self.raw); raw['kronos.direction'] = direction
        r = {**self.report, 'agent_type': role, 'action': 'FLAG_RISK' if role == 'risk' else 'PRESENT_CASE',
             'selected_evidence': [{'evidence_id': 'kronos.direction', 'priority': 1, 'use': mode}]}
        schema = v4.schema(role, v4.catalogue(raw), r['snapshot_id'])
        self.assertEqual(offered(schema, 'kronos.direction', mode), valid)
        if valid:
            self.assertEqual(v4.validate(r, role, r['snapshot_id'], raw)['selected_evidence'], r['selected_evidence'])
        else:
            with self.assertRaises(v4.ContractError) as caught: v4.validate(r, role, r['snapshot_id'], raw)
            self.assertEqual((caught.exception.code, caught.exception.path),
                             ('role_admissibility', '$.selected_evidence[0].use'))

    def test_frozen_failure_class_reproduces_not_exact_provider_json(self):
        with self.assertRaises(v4.ContractError) as caught:
            v4.validate(self.report, 'bull', self.report['snapshot_id'], self.raw)
        self.assertEqual(caught.exception.code, 'role_admissibility')
        self.assertEqual(caught.exception.path, '$.selected_evidence[0].use')
        self.assertFalse(offered(v4.schema('bull', self.cat), 'kronos.direction', 'SUPPORT'))

    def test_corrected_frozen_counter_passes(self):
        r = copy.deepcopy(self.report); r['selected_evidence'][0]['use'] = 'COUNTER'
        result = v4.build_result(v4.validate(r, 'bull', r['snapshot_id'], self.raw), 'bull', r['snapshot_id'], self.raw)
        self.assertEqual(result['direction'], 'BEARISH')
        self.assertEqual(result['support_level'], 'INSUFFICIENT')
        self.assertIn('NO_ROLE_ALIGNED_SUPPORT', result['uncertainty_flags'])
        self.assertEqual(result['resolved_facts'][0]['value'], 'down')

    def test_bull_bullish_support(self): self.check('bull', 'up', 'SUPPORT', True)
    def test_bull_bearish_support_rejected(self): self.check('bull', 'down', 'SUPPORT', False)
    def test_bull_bearish_counter(self): self.check('bull', 'down', 'COUNTER', True)
    def test_bear_bearish_support(self): self.check('bear', 'down', 'SUPPORT', True)
    def test_bear_bullish_support_rejected(self): self.check('bear', 'up', 'SUPPORT', False)
    def test_bear_bullish_counter(self): self.check('bear', 'up', 'COUNTER', True)
    def test_risk_admissible(self): self.check('risk', 'up', 'RISK', True)
    def test_risk_support_rejected(self): self.check('risk', 'up', 'SUPPORT', False)
    def test_unknown_enum(self): self.check('bull', 'down', 'COUNTER_EVIDENCE', False)

    def test_exhaustive_schema_validator_pair_equivalence(self):
        for raw in (self.raw, ar.evidence_catalog(self.fixture['record']['evidence'])):
            cat = v4.catalogue(raw)
            for role in v4.LIMITS:
                schema = v4.schema(role, cat)
                ar._strict_schema_preflight(schema)
                for key, item in cat.items():
                    for mode in (*v4.MODES, 'FAKE_MODE'):
                        valid = mode in item['role_compatibility'][role]
                        self.assertEqual(offered(schema, key, mode), valid, (role, key, mode))
                        r = {**self.report, 'agent_type': role,
                             'action': 'FLAG_RISK' if role == 'risk' else 'PRESENT_CASE',
                             'selected_evidence': [{'evidence_id': key, 'priority': 1, 'use': mode}]}
                        if valid: v4.validate(r, role, r['snapshot_id'], raw)
                        else:
                            with self.assertRaises(v4.ContractError): v4.validate(r, role, r['snapshot_id'], raw)

    def test_unknown_id_not_offered(self):
        for role in v4.LIMITS:
            self.assertFalse(offered(v4.schema(role, self.cat), 'FAKE_EVIDENCE_99', 'RISK'))

    def test_snapshot_schema_is_bound(self):
        schema = v4.schema('bull', self.cat, self.report['snapshot_id'])
        self.assertEqual(schema['properties']['snapshot_id']['enum'], [self.report['snapshot_id']])

    def test_empty_catalogue_only_abstention(self):
        schema = v4.schema('bull', {}, self.report['snapshot_id'])
        ar._strict_schema_preflight(schema)
        self.assertEqual(schema['properties']['action']['enum'], ['ABSTAIN'])
        self.assertEqual(schema['properties']['selected_evidence']['maxItems'], 0)
        r = {**self.report, 'action': 'ABSTAIN', 'selected_evidence': []}
        self.assertEqual(v4.validate(r, 'bull', r['snapshot_id'], {})['action'], 'ABSTAIN')

    def test_no_bull_support_does_not_force_fabrication(self):
        self.assertFalse(any('SUPPORT' in item['role_compatibility']['bull'] for item in self.cat.values()))
        r = {**self.report, 'action': 'ABSTAIN', 'selected_evidence': []}
        self.assertEqual(v4.validate(r, 'bull', r['snapshot_id'], self.raw)['action'], 'ABSTAIN')

    def test_schema_max_selections(self):
        for role, limit in v4.LIMITS.items():
            self.assertEqual(v4.schema(role, self.cat)['properties']['selected_evidence']['maxItems'], limit)

    def test_invalid_schema_union_or_bound_rejected(self):
        for schema in ({'anyOf': []}, {'anyOf': [{'type': 'string'}]},
                       {'type': 'array', 'items': {'type': 'string'}, 'maxItems': True}):
            with self.assertRaises(ValueError): ar._strict_schema_preflight(schema)

    def test_diagnostic_keeps_rejected_pair_without_prose(self):
        team = ar.AgentTeam(Path('unused'))
        with self.assertRaises(ar.ClaimValidationError) as caught:
            team._validate_report(self.report, 'bull', self.report['snapshot_id'], self.raw)
        d = caught.exception.diagnostic
        self.assertEqual(d['evidence_id'], 'kronos.direction')
        self.assertEqual(d['requested_use'], 'SUPPORT')
        self.assertEqual(d['allowed_uses'], ['COUNTER', 'RISK'])
        self.assertEqual(d['direction'], 'BEARISH')
        self.assertEqual(d['evidence_family'], 'FORECAST')
        self.assertEqual(d['action'], 'PRESENT_CASE')
        self.assertNotIn('optional_explanation', d)

    def test_diagnostic_does_not_leak_secret_or_path(self):
        r = copy.deepcopy(self.report)
        r['selected_evidence'][0] = {'evidence_id': 'D:\\private\\records', 'priority': 1, 'use': 'secret-example-value'}
        with patch.dict(os.environ, {'PRIVATE_TOKEN': 'secret-example-value'}):
            d = ar._v4_rejection_diagnostic(r, v4.ContractError('unknown_evidence_id', '$.selected_evidence[0].evidence_id'), 'bull', self.raw)
        text = json.dumps(d)
        self.assertNotIn('D:', text); self.assertNotIn('secret-example-value', text)

    def test_validator_version_invalidates_cache(self):
        team = ar.AgentTeam(Path('unused'))
        key = team._key(self.report['snapshot_id'], 'bull')
        with patch.object(v4, 'VALIDATOR_VERSION', 'evidence_selection_validator_v1'):
            self.assertNotEqual(key, team._key(self.report['snapshot_id'], 'bull'))

    def test_daily_count_no_longer_blocks_v4_team_health(self):
        with tempfile.TemporaryDirectory() as folder:
            team = ar.AgentTeam(Path(folder), config=ar.AgentConfig(daily_call_limit=1), client_factory=Client)
            for _ in range(15): self.assertTrue(team.usage.reserve('openai_agents', None))
            result = team.run(self.fixture['record'])
            self.assertEqual(result['agents_completed'], 3)
            self.assertEqual(result['api_calls'], 3)
            self.assertEqual(team.usage.totals('openai_agents')[0], 18)
            self.assertEqual(team.health(self.fixture['record'])['status'], 'HEALTHY')
            self.assertFalse(team.preflight(self.fixture['record'])['output_budget']['daily_limit_enforced'])

    def test_workflow_and_retry_caps_preserved(self):
        def malformed(role, report, count): return 'not-json'
        with tempfile.TemporaryDirectory() as folder:
            client = Client(malformed); team = ar.AgentTeam(Path(folder), client_factory=lambda: client)
            result = team.run(self.fixture['record'])
            self.assertEqual(result['api_calls'], 6)
            self.assertTrue(all(item['attempts'] == 2 for item in result['agents'].values()))
            self.assertEqual(team._workflow_calls_remaining, 0)
            rows = [json.loads(p.read_text()) for p in (team.root/'attempts').glob('*.json')]
            self.assertEqual(sorted(r['workflow_calls_remaining'] for r in rows), list(range(6)))

    def test_bull_only_cap_and_daily_count(self):
        with tempfile.TemporaryDirectory() as folder:
            client = Client(lambda role, report, count: 'not-json')
            team = ar.AgentTeam(Path(folder), client_factory=lambda: client)
            for _ in range(12): team.usage.reserve('openai_agents', None)
            result = team.run_bull_only(self.fixture['record'])
            self.assertEqual(result['api_calls'], 2)
            self.assertEqual(len(client.calls), 2)
            self.assertTrue(all(c['text']['format']['name'].startswith('bull') for c in client.calls))

    def test_workflow_cap_checks_before_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            team = ar.AgentTeam(Path(folder), client_factory=lambda: self.fail('Provider must not be created'))
            team._active = True; team._workflow_calls_remaining = 0
            with self.assertRaises(ar.AgentError) as caught: team._call('bull', b'{}', {}, {}, {})
            self.assertEqual(caught.exception.code, 'COST_LIMIT')
            self.assertFalse((team.root/'openai_usage.sqlite3').exists())

    def test_optional_prose_stays_nonblocking_full_team(self):
        with tempfile.TemporaryDirectory() as folder:
            result = full_team(self.fixture, Path(folder), lambda role, report, count: {**report, 'optional_explanation': 'RSI 999.'})
            self.assertTrue(all(result['checks'].values()))

    def test_provider_retries_remain_disabled(self):
        with tempfile.TemporaryDirectory() as folder, patch('openai.OpenAI') as constructor:
            constructor.return_value = Client()
            team = ar.AgentTeam(Path(folder)); team.run_bull_only(self.fixture['record'])
            self.assertEqual(constructor.call_args.kwargs['max_retries'], 0)
            self.assertEqual(ar.MAX_RETRIES, 1)
