"""Strict structured bindings and sanitized latest live-shape replay; offline only."""
from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from app import agent_research as ar
from app import structured_claims as sc
from app.evidence_snapshot import canonical_bytes
from research.tests.test_phase7_agents import structured_fact, typed_claim
from research.tests.test_fixture_serialization_repair import mocked_team, wire, report_for
from research.tests.fixtures.dual_retest_fixtures import build_fixture

FIXTURES = Path(__file__).parent / 'fixtures'


def frozen_fixture(test):
    return json.loads((FIXTURES / f'dual_live_retest_{test}_v2.json').read_text())


def latest_live_replays():
    """Retained diagnostic claim shapes, not invented complete provider responses."""
    return [
        ('bull', 'Technicals show a bullish regime and multiple bullish indicators.', 'FACT', 'TECHNICAL',
         ['technicals.regime', *[f'technicals.indicator.{i}' for i in (0, 1, 2, 3, 5)]],
         [structured_fact('market_regime', 'TRENDING_BULL', 'state', ['technicals.regime'], evidence_type='TECHNICAL')]),
        ('bull', 'News impact is limited to a single product partnership announcement with modest positive impact.',
         'FACT', 'NEWS', ['news.article.0', 'news.event.0'], []),
        ('bear', 'Technicals regime is TRENDING_BULL with bullish indicators.', 'FACT', 'TECHNICAL',
         ['technicals.regime', 'technicals.trend'],
         [structured_fact('market_regime', 'TRENDING_BULL', 'state', ['technicals.regime'], evidence_type='TECHNICAL')]),
        ('bear', 'Kronos forecast direction is up.', 'FACT', 'FORECAST', ['kronos.direction'],
         [structured_fact('forecast_direction', 'up', 'state', ['kronos.direction'])]),
        ('risk', 'Kronos direction is up and forecast_final_close is 101.2 (forecast_pct_change 1.2).',
         'NUMERICAL_FACT', 'FORECAST', ['kronos.direction', 'kronos.forecast_final_close', 'kronos.forecast_pct_change'],
         [structured_fact('forecast_final_price', 101.2, 'price', ['kronos.forecast_final_close']),
          structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change'])]),
        ('risk', 'Kronos direction is up, forecast_final_close equals 101.2 (FORECAST).',
         'NUMERICAL_FACT', 'FORECAST', ['kronos.direction', 'kronos.forecast_final_close', 'kronos.model_id'],
         [structured_fact('forecast_final_price', 101.2, 'price', ['kronos.forecast_final_close'])]),
    ]


class StructuredClaimRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = frozen_fixture('A')
        self.catalog = ar.evidence_catalog(self.fixture['record']['evidence'])

    def check(self, claim, role='bull', catalog=None):
        return ar._validate_claim(claim, role, 'offline.structured', self.catalog if catalog is None else catalog)

    def test_latest_six_live_shapes_reject_corrected_split_shapes_pass(self):
        for role, text, kind, family, ids, corrections in latest_live_replays():
            with self.subTest(role=role, text=text):
                legacy = typed_claim(text, ids, claim_type=kind, support_type='DIRECT', evidence_type=family)
                with self.assertRaises((ar.ClaimValidationError, ar.NumericalGroundingError)):
                    self.check(legacy, role)
                if not corrections:
                    corrections = [structured_fact('news_title', self.catalog['news.article.0']['title'], 'text',
                        ['news.article.0'], evidence_type='NEWS'),
                        typed_claim('The partnership may provide a modest constructive context, not measured price impact.',
                                    ['news.article.0'], evidence_type='NEWS')]
                for corrected in corrections:
                    self.assertEqual(self.check(corrected, role), corrected)

    def test_fact_bindings_symmetric_for_all_roles(self):
        for role in ar.AGENTS:
            for claim in [structured_fact('forecast_direction', 'up', 'state', ['kronos.direction']),
                          structured_fact('forecast_final_price', 101.2, 'price', ['kronos.forecast_final_close']),
                          structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change']),
                          structured_fact('rsi', self.catalog['technicals.indicator.0']['value'], 'unitless',
                                          ['technicals.indicator.0'], evidence_type='TECHNICAL')]:
                self.check(claim, role)

    def test_wrong_value_field_unit_sign_rejected(self):
        base = structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change'])
        for changes in ({'value': 15}, {'value': -1.2}, {'unit': 'unitless'}, {'unit': 'INR'},
                        {'field_key': 'rsi'}, {'direction': 'downside'}, {'value': True},
                        {'value': float('nan')}, {'value': float('inf')}, {'value': '1.2'},
                        {'field_key': 'profit_growth'}, {'field_key': []}, {'value': None}):
            with self.subTest(changes=changes), self.assertRaises(ar.NumericalGroundingError):
                self.check({**base, **changes})

    def test_price_rsi_and_volume_cannot_cross_bind(self):
        for key, value, unit, refs, family in [
                ('rsi', 1.2, 'unitless', ['kronos.forecast_pct_change'], 'FORECAST'),
                ('observed_price', 100.1, 'price', ['kronos.last_observed_close'], 'FORECAST'),
                ('volume', 100, 'volume_units', ['kronos.last_observed_close'], 'FORECAST'),
                ('forecast_final_price', 101.2, 'USD', ['kronos.forecast_final_close'], 'FORECAST'),
                ('rsi', 99, 'unitless', ['technicals.indicator.0'], 'TECHNICAL')]:
            with self.subTest(key=key), self.assertRaises(ar.NumericalGroundingError):
                self.check(structured_fact(key, value, unit, refs, evidence_type=family))

    def test_unsupported_state_prose_and_interpretation_as_fact_rejected(self):
        for claim in [structured_fact('forecast_direction', 'down', 'state', ['kronos.direction']),
                      structured_fact('technical_trend', 'strengthening', 'state', ['technicals.trend'], evidence_type='TECHNICAL'),
                      typed_claim('Demand is strengthening.', ['news.article.0'], claim_type='FACT',
                                  support_type='DIRECT', evidence_type='NEWS')]:
            with self.assertRaises(ar.ClaimValidationError): self.check(claim)
        c = structured_fact('forecast_direction', 'up', 'state', ['kronos.direction'])
        for text in ('The forecast is down.', 'The forecast is up and will rise.', 'up'):
            with self.assertRaises(ar.ClaimValidationError): self.check({**c, 'text': text})

    def test_wrong_ids_family_missing_ids_and_mixed_direct_rejected(self):
        base = structured_fact('forecast_direction', 'up', 'state', ['kronos.direction'])
        for changes in ({'evidence_ids': []}, {'evidence_ids': ['missing']}, {'evidence_type': 'NEWS'},
                        {'evidence_type': 'MULTI_SOURCE', 'evidence_ids': ['kronos.direction', 'technicals.trend']}):
            with self.assertRaises(ar.ClaimValidationError): self.check({**base, **changes})

    def test_exact_aliases_and_downside_equivalence_only(self):
        catalog = {**self.catalog, 'kronos.forecast_pct_change': -2.4}
        for alias in ('forecast_return_pct', 'forecast_pct', 'forecast_pct_change', 'forecast_percentage'):
            self.check(structured_fact(alias, -2.4, 'percent', ['kronos.forecast_pct_change']), catalog=catalog)
            self.check(structured_fact(alias, 2.4, 'percent', ['kronos.forecast_pct_change'], direction='downside'), catalog=catalog)
            with self.assertRaises(ar.NumericalGroundingError):
                self.check(structured_fact(alias, -2.4, 'percent', ['kronos.forecast_pct_change'], direction='upside'), catalog=catalog)
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(structured_fact('forecast_returns', -2.4, 'percent', ['kronos.forecast_pct_change']), catalog=catalog)

    def test_all_cited_bindings_must_agree(self):
        catalog = {**self.catalog, 'market_data.last_observed_close': 99}
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(structured_fact('observed_price', 100, 'price',
                ['kronos.last_observed_close', 'market_data.last_observed_close'], evidence_type='MULTI_SOURCE'), catalog=catalog)

    def test_explicit_currency_requires_cited_currency_metadata(self):
        catalog = {**self.catalog, 'market_data.last_observed_close': 100, 'market_data.currency': 'INR'}
        c = structured_fact('observed_price', 100, 'INR',
                            ['market_data.last_observed_close', 'market_data.currency'], evidence_type='MARKET_DATA')
        self.check(c, catalog=catalog)
        for changes in ({'unit': 'USD'}, {'evidence_ids': ['market_data.last_observed_close']}):
            with self.assertRaises(ar.NumericalGroundingError): self.check({**c, **changes}, catalog=catalog)

    def test_interpretations_numbers_and_fact_fields_remain_strict(self):
        c = typed_claim('The forecast return of 1.2% may support the case.', ['kronos.forecast_pct_change'])
        self.check(c)
        with self.assertRaises(ar.NumericalGroundingError): self.check({**c, 'text': 'The forecast return of 15% may support the case.'})
        with self.assertRaises(ar.ClaimValidationError): self.check({**c, 'field_key': 'forecast_return_pct', 'value': 1.2, 'unit': 'percent'})
        with self.assertRaises(ar.ClaimValidationError): self.check({**c, 'support_type': 'DIRECT'})

    def test_closed_schema_nullable_fields_and_old_shape_rejected(self):
        for role in ar.AGENTS:
            schema = ar.output_schema(role, ar.allowed_evidence_ids(self.catalog))
            ar._strict_schema_preflight(schema)
            json.dumps(schema, allow_nan=False)
        c = structured_fact('forecast_direction', 'up', 'state', ['kronos.direction'])
        with self.assertRaises(ar.ClaimValidationError):
            self.check({k: v for k, v in c.items() if k not in sc.STRUCTURED_FIELDS})
        with self.assertRaises(ValueError): ar._strict_schema_preflight({'type': ['string', 'object', 'null']})

    def test_real_indicator_labels_have_exact_supported_bindings(self):
        for key, (labels, unit) in sc.INDICATOR_FIELDS.items():
            for label in labels:
                cat = {'technicals.indicator.99': {'indicator': label, 'value': 0.5}}
                self.check(structured_fact(key, 0.5, unit, list(cat), evidence_type='TECHNICAL'), catalog=cat)
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(structured_fact('atr', 0.5, 'price', ['technicals.indicator.99'], evidence_type='TECHNICAL'),
                       catalog={'technicals.indicator.99': {'indicator': 'Almost ATR14', 'value': 0.5}})

    def test_explicit_false_states_cannot_hide_in_interpretation(self):
        for text, ref, family in [('Kronos direction is down and may support caution.', 'kronos.direction', 'FORECAST'),
                                 ('Technical trend is bearish and may support caution.', 'technicals.trend', 'TECHNICAL'),
                                 ('Regime is TRENDING_BEAR and may support caution.', 'technicals.regime', 'TECHNICAL')]:
            with self.assertRaises(ar.ClaimValidationError): self.check(typed_claim(text, [ref], evidence_type=family))
        self.check(typed_claim('Kronos direction is up and may support a constructive case.', ['kronos.direction']))

    def test_directional_numeric_prose_stays_mathematically_grounded(self):
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(typed_claim('The 1.2% downside forecast may support caution.', ['kronos.forecast_pct_change']))
        cat = {**self.catalog, 'kronos.forecast_pct_change': -2.4}
        self.check(typed_claim('The 2.4% downside forecast may support caution.', ['kronos.forecast_pct_change']), catalog=cat)
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(typed_claim('The -2.4% upside forecast may support caution.', ['kronos.forecast_pct_change']), catalog=cat)

    def test_invalid_structured_diagnostics_do_not_leak_secrets_or_nonfinite_values(self):
        secret = 'offline-test-secret-value'
        c = structured_fact('forecast_return_pct', float('nan'), 'percent', ['kronos.forecast_pct_change'])
        with self.assertRaises(ar.NumericalGroundingError) as error: self.check(c)
        json.dumps(error.exception.diagnostic, allow_nan=False)
        c = structured_fact('forecast_direction', secret, 'state', ['kronos.direction'])
        with patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
            with self.assertRaises(ar.ClaimValidationError) as error: self.check(c)
            self.assertNotIn(secret, json.dumps(error.exception.diagnostic))
        c['evidence_ids'] = [{'bad': 'shape'}]
        with self.assertRaises(ar.ClaimValidationError): self.check(c)

    def test_precise_equality_and_non_scalar_source_rejection(self):
        cat = {**self.catalog, 'kronos.forecast_pct_change': 1.20}
        self.check(structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change']), catalog=cat)
        cat['kronos.forecast_pct_change'] = {'value': 1.2}
        with self.assertRaises(ar.NumericalGroundingError):
            self.check(structured_fact('forecast_return_pct', 1.2, 'percent', ['kronos.forecast_pct_change']), catalog=cat)

    def test_headline_numbers_cannot_bypass_structured_numeric_binding(self):
        title = 'TESTCO offers 15% upside'
        cat = {'news.article.0': {'title': title}}
        with self.assertRaises(ar.ClaimValidationError):
            self.check(structured_fact('news_title', title, 'text', ['news.article.0'], evidence_type='NEWS'), catalog=cat)

    def test_extreme_numbers_fail_without_erasing_diagnostics(self):
        c = structured_fact('forecast_return_pct', 10**500, 'percent', ['kronos.forecast_pct_change'])
        with self.assertRaises(ar.NumericalGroundingError) as error: self.check(c)
        json.dumps(error.exception.diagnostic, allow_nan=False)
        c['confidence'] = 10**500
        with self.assertRaises(ar.ClaimValidationError): self.check(c)

    def test_claim_identity_includes_structured_value_and_field(self):
        f = copy.deepcopy(self.fixture)
        report = report_for('bull', f)
        first = ar.claim_metadata(report, 'bull')[0]['claim_sha256']
        report['argument']['value'] = 'down'
        self.assertNotEqual(first, ar.claim_metadata(report, 'bull')[0]['claim_sha256'])
        self.assertEqual(sc.claim_text(structured_fact('forecast_pct', 1.2, 'percent', ['kronos.forecast_pct_change'])),
                         'forecast_return_pct = 1.2 percent')

    def test_dashboard_renders_structured_facts_and_all_material_risk_categories(self):
        js = (FIXTURES.parents[2] / 'app/dashboard.js').read_text(encoding='utf-8')
        for marker in ('FACT', 'NUMERICAL_FACT', 'value.field_key', 'value.value', 'value.unit',
                       "['risk_factors', 'conflicts', 'model_risks', 'data_risks', 'event_risks']",
                       'riskClaims.map(claimText)', 'item.textContent'):
            self.assertIn(marker, js)

    def test_schema_prompt_and_numeric_validator_versions_invalidate_cache(self):
        team = LegacyAgentTeam(Path('unused')); digest = self.fixture['record']['snapshot_id']
        key = team._key(digest, 'bull')
        for attr, value in [('SCHEMA_VERSION', 'agent_output_v2'), ('NUMERICAL_VALIDATOR_VERSION', 'numerical_grounding_v3')]:
            with patch.object(ar.v3 if attr == 'SCHEMA_VERSION' else ar, attr, value): self.assertNotEqual(key, team._key(digest, 'bull'))
        with patch.dict(ar.LEGACY_PROMPT_VERSIONS, {'bull': 'bull_agent_prompt_v7'}):
            self.assertNotEqual(key, team._key(digest, 'bull'))

    def test_frozen_bytes_hashes_and_full_mock_teams_at_frozen_clock(self):
        manifest = json.loads((FIXTURES.parents[1] / 'results/healthcheck_postrepair/dual_live_retest_preflight_v2.json').read_text())
        for test in ('A', 'B'):
            f = frozen_fixture(test)
            expected = 21420 if test == 'A' else 21834
            self.assertEqual(len(wire(f['record'])), expected)
            before = canonical_bytes(f)
            # Replay a historical frozen fixture at its recorded time; do not refresh or bypass the guard.
            real_guard = ar.assert_fresh_snapshot
            stamp = datetime.fromisoformat(f['record']['created_at'])
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'}), \
                    patch.object(ar, 'assert_fresh_snapshot', side_effect=lambda r: real_guard(r, now=stamp)):
                outcome = mocked_team(f, Path(tmp))
                self.assertTrue(all(outcome['checks'].values()), outcome['checks'])
                self.assertEqual(outcome['result']['agents_completed'], 3)
                self.assertEqual(outcome['external_calls'], 0)
            self.assertEqual(before, canonical_bytes(f))
            m = manifest['fixtures'][test]
            self.assertEqual(m['snapshot_id'], f['record']['snapshot_id'])
            self.assertEqual(m['wire_sha256'], hashlib.sha256(wire(f['record'])).hexdigest())
            self.assertEqual(m['fixture_file_sha256'], hashlib.sha256((FIXTURES / f'dual_live_retest_{test}_v2.json').read_bytes()).hexdigest())


if __name__ == '__main__': unittest.main()
