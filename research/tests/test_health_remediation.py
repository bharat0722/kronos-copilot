"""Offline production-sized reliability regressions. No real model/provider execution."""
from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam

import copy
import hashlib
import http.client
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import agent_research
from app.agent_research import AgentConfig, AgentError, AgentTeam, assert_fresh_snapshot, validate_concise
from app.evidence_fusion import EvidenceFusionEngine
from app.evidence_snapshot import canonical_bytes, snapshot_id
from research.tests.test_phase7_agents import concise_report, evidence, snapshot, valid_report
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response


def production_record():
    content = evidence()
    stamp = datetime.now(timezone.utc).isoformat()
    content['instrument'].update(canonical_symbol='NSE:TESTCO', provider_symbol='TESTCO.NS')
    content['market_data'].update(retrieved_at=stamp, capture_id='synthetic-production-v1', interval='5m')
    content['technicals']['as_of'] = stamp
    content['technicals']['values'] = [
        {'indicator': name, 'value': 55.0, 'signal': 'bullish', 'strength': 0.55,
         'reason': 'Synthetic deterministic evidence, not measured market performance.'}
        for name in ('RSI14', 'EMA20', 'EMA50', 'SMA20', 'SMA50', 'MACD', 'MACD_SIGNAL',
                     'BOLLINGER', 'ATR', 'ROC', 'VOLUME_SMA', 'VOLUME_SPIKE')]
    content['news'].update(retrieved_at=stamp, evidence_status='GOLD_AVAILABLE', provider='synthetic')
    content['news']['article_evidence'] = [
        {'id': f'fictional-{i}', 'title': f'TESTCO fictional event {i}', 'published_at': stamp,
         'url': f'https://example.org/synthetic/{i}', 'source': 'Synthetic source', 'provider': 'offline',
         'summary': 'Synthetic neutral event context. ' * 12, 'relevance': 0.8,
         'source_quality': 'UNKNOWN', 'event_type': 'other', 'sentiment': 'neutral'} for i in range(25)]
    return snapshot(content)


class HealthRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = production_record()
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'})
        env.start()
        self.addCleanup(env.stop)

    def team(self, fail=()):
        client = MockClient(lambda role: mock_response(role, self.record['snapshot_id'],
                    status='incomplete', incomplete_reason='max_output_tokens') if role in fail else
                    mock_response(role, self.record['snapshot_id']))
        return LegacyAgentTeam(self.root / 'agents', client_factory=lambda: client), client

    def test_production_size_and_budget_preflight(self):
        team, client = self.team()
        preflight = team.preflight(self.record)
        self.assertGreater(preflight['input_bytes'], 30000)
        self.assertLessEqual(preflight['input_bytes'], 48000)
        self.assertGreaterEqual(len(agent_research.evidence_catalog(self.record['evidence'])), 60)
        self.assertEqual(preflight['output_budget']['status'], 'OK')
        self.assertEqual(preflight['output_budget']['team_max_output_tokens'], 9600)
        self.assertEqual(preflight['output_budget']['daily_max_output_tokens'], 19200)
        self.assertEqual(client.calls, [])

    def test_bad_budget_stops_before_client(self):
        team = LegacyAgentTeam(self.root, config=AgentConfig(max_output_tokens=900), client_factory=lambda: self.fail('No call'))
        with self.assertRaisesRegex(AgentError, 'budget'):
            team.run(self.record)
        self.assertFalse((self.root / 'openai_usage.sqlite3').exists())

    def test_team_state_write_failure_prevents_call_and_clears_running(self):
        team, client = self.team()
        original = agent_research._atomic_json
        def failed(path, value):
            if path.parent.name == 'teams':
                raise OSError('Synthetic status store failure')
            original(path, value)
        with patch.object(agent_research, '_atomic_json', side_effect=failed):
            with self.assertRaises(AgentError) as error:
                team.run(self.record)
        self.assertEqual(error.exception.code, 'LEDGER_UNAVAILABLE')
        self.assertFalse(team._active)
        self.assertEqual(client.calls, [])

    def test_concise_validation_preserves_typed_contract(self):
        for role in ('bull', 'bear', 'risk'):
            report = concise_report(valid_report(role, self.record['snapshot_id']))
            agent_research.validate_output(report, role, self.record['snapshot_id'],
                                          agent_research.evidence_catalog(self.record['evidence']))
            validate_concise(report, role)
            self.assertLess(len(json.dumps(report)) / 4, 900)  # Explicit byte/4 heuristic, not API usage.
            if role != 'risk':
                report['key_factors'] = [copy.deepcopy(report['argument'])]
            else:
                report['data_risks'] = [copy.deepcopy(report['risk_factors'][0])]
            with self.assertRaises(ValueError):
                validate_concise(report, role)

    def test_complete_restart_and_fusion_refresh_immutable(self):
        team, client = self.team()
        engine = EvidenceFusionEngine(self.root / 'fusion')
        before = canonical_bytes(self.record)
        missing = engine.fuse(self.record, agent_result=team.result(self.record))
        result = team.run(self.record)
        self.assertEqual(result['team_status'], 'COMPLETE')
        self.assertEqual(len(client.calls), 3)
        restarted = LegacyAgentTeam(self.root / 'agents', client_factory=lambda: self.fail('Cache only'))
        self.assertEqual(restarted.result(self.record)['team_status'], 'COMPLETE')
        self.assertEqual(restarted.health(self.record)['rows'], 3)
        fused = engine.fuse(self.record, agent_result=restarted.result(self.record))
        self.assertNotEqual(missing['result_hash'], fused['result_hash'])
        self.assertFalse(any(item in fused['missing_evidence'] for item in ('AGENT_BULL', 'AGENT_BEAR', 'AGENT_RISK')))
        self.assertEqual(canonical_bytes(self.record), before)

    def test_truncation_failed_restart_six_attempts_no_cache(self):
        team, client = self.team(('bull', 'bear', 'risk'))
        result = team.run(self.record)
        self.assertEqual(result['team_status'], 'FAILED')
        self.assertEqual(len(client.calls), 6)
        self.assertTrue(all(call['max_output_tokens'] == 1600 for call in client.calls))
        self.assertEqual(list((team.root / 'cache').glob('*.json')), [])
        rows = [json.loads(path.read_text()) for path in (team.root / 'attempts').glob('*.json')]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['failure_stage'] == 'OUTPUT_TRUNCATED' for row in rows))
        self.assertTrue(all(row['completion_reason'] == 'max_output_tokens' and row['max_output_tokens'] == 1600 for row in rows))
        restored = LegacyAgentTeam(team.root)
        self.assertEqual(restored.result(self.record)['team_status'], 'FAILED')
        self.assertEqual(restored.health(self.record)['errors'], ['OUTPUT_TRUNCATED'] * 3)
        self.assertEqual(restored.health()['team_status'], 'FAILED')

    def test_partial_restart_new_snapshot_distinction(self):
        team, client = self.team(('risk',))
        result = team.run(self.record)
        self.assertEqual(result['team_status'], 'PARTIAL')
        restored = LegacyAgentTeam(team.root)
        self.assertEqual(restored.result(self.record)['team_status'], 'PARTIAL')
        self.assertEqual(restored.health(self.record)['rows'], 2)
        changed = copy.deepcopy(self.record)
        changed['evidence']['kronos']['direction'] = 'down'
        changed['snapshot_id'] = snapshot_id(changed['evidence'])
        self.assertEqual(restored.result(changed)['team_status'], 'READY')
        fused = EvidenceFusionEngine(self.root / 'fusion').fuse(self.record, agent_result=restored.result(self.record))
        self.assertIn('AGENT_RISK', fused['missing_evidence'])

    def test_expired_future_missing_and_stale_acquisition_stop_before_call(self):
        for modification in ('expired', 'future', 'missing', 'market'):
            record = copy.deepcopy(self.record)
            stamp = (datetime.now(timezone.utc) + timedelta(hours=2 if modification == 'future' else -2)).isoformat()
            if modification == 'missing':
                record.pop('created_at')
            elif modification == 'market':
                record['evidence']['market_data']['retrieved_at'] = stamp
                record['snapshot_id'] = snapshot_id(record['evidence'])
            else:
                record['created_at'] = stamp
            team = LegacyAgentTeam(self.root / modification, client_factory=lambda: self.fail('No model call'))
            with self.assertRaises(AgentError) as error:
                team.run(record)
            self.assertEqual(error.exception.code, 'STALE_EVIDENCE')
            self.assertFalse(team.root.exists())

    def test_interrupted_running_restores_failed_not_ready(self):
        team, _ = self.team()
        digest = self.record['snapshot_id']
        agent_research._atomic_json(team.root / 'teams' / f'{digest}.json',
            {'snapshot_id': digest, 'team_status': 'RUNNING', 'agents': {}, 'run_id': 'interrupted'})
        agent_research._atomic_json(team.root / 'team_latest.json', {'snapshot_id': digest})
        self.assertEqual(LegacyAgentTeam(team.root).result(self.record)['team_status'], 'FAILED')
        self.assertEqual(LegacyAgentTeam(team.root).health()['team_status'], 'FAILED')

    def test_current_identity_and_public_path_sanitization(self):
        from app import server
        team, client = self.team()
        with patch.object(server, 'EVIDENCE_DIR', self.root), patch.object(server, 'current_agent_snapshot', return_value=self.record):
            with self.assertRaises(AgentError) as error:
                server.current_paid_agent_snapshot(self.record['snapshot_id'])
            self.assertEqual(error.exception.code, 'STALE_EVIDENCE')
            agent_research._atomic_json(self.root / 'current.json', {'snapshot_id': self.record['snapshot_id']})
            self.assertEqual(server.current_paid_agent_snapshot(self.record['snapshot_id']), self.record)
        self.assertNotIn('secret', server.public_error(FileNotFoundError('D:\\private\\secret.env')))
        self.assertNotIn('D:', server.public_error(ValueError('D:\\private\\data.csv')))
        self.assertEqual(client.calls, [])

    def test_http_team_fusion_status_and_sanitized_dashboard(self):
        from app import server
        team, client = self.team()
        engine = EvidenceFusionEngine(self.root / 'fusion')
        pipeline = SimpleNamespace(snapshot=lambda: {'stages': {}})
        news = SimpleNamespace(pipeline_stage=lambda: {'status': 'HEALTHY', 'symbol': 'TESTCO.NS'})
        with patch.object(server, 'AGENT_TEAM', team), patch.object(server, 'FUSION_ENGINE', engine), \
             patch.object(server, 'PRODUCT_PIPELINE', pipeline), patch.object(server, 'NEWS_SERVICE', news), \
             patch.object(server, 'current_agent_snapshot', return_value=self.record), \
             patch.object(server, 'current_paid_agent_snapshot', return_value=self.record), \
             patch.object(server, 'read_snapshot', return_value=self.record), patch.object(server, 'load_local_key'):
            httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.DashboardHandler)
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            try:
                def request(method, url, body=None):
                    conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=10)
                    conn.request(method, url, body=body, headers={'Host': f'127.0.0.1:{httpd.server_port}',
                                 'X-Kronos-Request': 'dashboard', 'Sec-Fetch-Site': 'same-origin', 'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    status, result = response.status, json.loads(response.read())
                    conn.close()
                    return status, result
                status, result = request('POST', '/api/agents/run', json.dumps({'snapshot_id': self.record['snapshot_id']}))
                self.assertEqual(status, 200)
                self.assertEqual(result['team_status'], 'COMPLETE')
                status, fused = request('GET', '/api/fusion?id=' + self.record['snapshot_id'])
                self.assertEqual(status, 200)
                self.assertNotIn('AGENT_RISK', fused['missing_evidence'])
                _, health = request('GET', '/api/pipeline?id=' + self.record['snapshot_id'])
                self.assertEqual(health['stages']['agents']['team_status'], 'COMPLETE')
                self.assertEqual(health['stages']['fusion']['status'], 'HEALTHY')
                self.assertEqual(health['stages']['news']['status'], 'HEALTHY')
                changed = copy.deepcopy(self.record)
                changed['evidence']['kronos']['direction'] = 'down'
                changed['evidence']['instrument']['provider_symbol'] = 'OTHER.NS'
                changed['snapshot_id'] = snapshot_id(changed['evidence'])
                with patch.object(server, 'current_agent_snapshot', return_value=changed):
                    _, newer = request('GET', '/api/pipeline?id=' + changed['snapshot_id'])
                    self.assertEqual(newer['stages']['fusion']['status'], 'STALE')
                    self.assertEqual(newer['stages']['news']['status'], 'STALE')
                with patch.object(server, 'load_summary', side_effect=FileNotFoundError('D:\\private\\x')):
                    _, error = request('GET', '/api/dashboard')
                    self.assertNotIn('D:', json.dumps(error))
            finally:
                httpd.shutdown()
                httpd.server_close()
                worker.join(3)
        self.assertEqual(len(client.calls), 3)

    def test_mocked_wrapper_horizons_context_and_malformed_display(self):
        import pandas as pd
        import first_forecast as wrapper
        from app import server
        history = pd.DataFrame({'timestamps': pd.date_range('2026-10-08 09:15', periods=400, freq='5min', tz='Asia/Kolkata'),
                               **{name: [100.0] * 400 for name in wrapper.FEATURES}})
        input_file = self.root / 'synthetic.csv'
        history.to_csv(input_file, index=False)
        seen = []
        def predict(frame, timestamps, bars, **kwargs):
            seen.append((len(frame), bars))
            return pd.DataFrame({'timestamps': timestamps, **{name: [100.0] * bars for name in wrapper.FEATURES}}), 0.0
        with patch.object(wrapper, 'OUTPUTS_DIR', self.root), patch.object(wrapper, 'predict_with_kronos', side_effect=predict):
            for horizon in (24, 75, 120):
                result = wrapper.run_kronos_forecast(input_file, input_label='synthetic', forecast_bars=horizon)
                self.assertEqual(result['forecast_rows'], horizon)
        self.assertTrue(all(context == wrapper.LOOKBACK_BARS for context, _ in seen))
        invalid = self.root / 'invalid.csv'
        invalid.write_text('timestamps,close\n2026-10-08,100\n')
        with self.assertRaises(ValueError):
            wrapper.prepare_market_data(invalid)

    def test_frontend_state_timeout_and_scoped_pipeline_contract(self):
        script = (Path(__file__).resolve().parents[2] / 'app/dashboard.js').read_text(encoding='utf-8')
        for marker in ('payload.team_status', "teamStatus === 'FAILED'", 'new AbortController()',
                       '210000', 'loadFusion(snapshotId)', 'state.agentEligible', '?id=${encodeURIComponent(state.agentSnapshotId)}',
                       'entry.failure_stage', 'No accepted analysis.', 'entry.run_id'):
            self.assertIn(marker, script)

    def test_eligibility_changes_between_roles_prevent_more_requests(self):
        team, client = self.team()
        checks = [0]
        def eligible():
            checks[0] += 1
            if checks[0] > 1:
                raise AgentError('STALE_EVIDENCE', 'Evidence changed. Refresh the research view before running agents.')
        result = team.run(self.record, eligibility_check=eligible)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result['team_status'], 'PARTIAL')
        self.assertEqual(result['agents']['bear']['error_code'], 'STALE_EVIDENCE')

    def test_live_running_status_and_cancel_recover_without_extra_calls(self):
        team, client = self.team()
        begun, release = threading.Event(), threading.Event()
        original = client.create
        def blocked(**kwargs):
            begun.set()
            release.wait(3)
            return original(**kwargs)
        client.responses = SimpleNamespace(create=blocked)
        cancelled = threading.Event()
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(team.run(self.record, cancelled=cancelled)))
        worker.start()
        self.assertTrue(begun.wait(3))
        try:
            self.assertEqual(team.result(self.record)['team_status'], 'RUNNING')
            self.assertEqual(team.health(self.record)['status'], 'RUNNING')
            cancelled.set()
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(outcome[0]['team_status'], 'PARTIAL')

    def test_stale_unrun_is_not_ready(self):
        team, _ = self.team()
        record = copy.deepcopy(self.record)
        record['created_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.assertEqual(team.result(record)['team_status'], 'NOT_RUN')
        self.assertFalse(team.result(record)['eligible'])
        self.assertEqual(team.health(record)['status'], 'STALE')

    def test_pipeline_operational_and_research_status_are_separate(self):
        import pandas as pd
        from app.product_pipeline import ProductPipeline
        from research.market_data import ProviderResult, MarketDataRequest
        pipeline = ProductPipeline(self.root / 'pipeline')
        bars = pd.DataFrame({'timestamp': pd.date_range('2026-10-08 09:15', periods=400, freq='5min', tz='Asia/Kolkata'),
                             **{name: [100.0] * 400 for name in ('open', 'high', 'low', 'close', 'volume', 'amount')}})
        captured = pipeline.capture(ProviderResult(provider='synthetic', request=MarketDataRequest('TESTCO.NS'),
            bars=bars, raw_payload=None, provenance={'retrieved_at': datetime.now(timezone.utc).isoformat()},
            quality={'state': 'WARN', 'issues': [{'code': 'SYNTHETIC_WARNING'}]}, health={'status': 'HEALTHY'}))
        pipeline.complete(captured, bars.rename(columns={'timestamp': 'timestamps'}),
                          {'chart': {'forecast': []}, 'summary_fingerprint': 'synthetic', 'model': 'synthetic'})
        stage = pipeline.snapshot()['stages']['intelligence']
        self.assertEqual(stage['status'], 'HEALTHY')
        self.assertIn('Ensemble remains research-only', stage['limitations'])
        manifest = json.loads(pipeline._latest.read_text())
        manifest['updated_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        pipeline._write_latest(manifest)
        status = pipeline.snapshot()['stages']
        self.assertEqual(status['bronze']['status'], 'STALE')
        self.assertEqual(status['silver']['status'], 'STALE')

    def test_fusion_mixed_is_operational_success_but_old_run_stale(self):
        engine = EvidenceFusionEngine(self.root / 'fusion')
        engine.fuse(self.record)
        self.assertEqual(engine.health()['status'], 'HEALTHY')
        self.assertEqual(engine.health()['research_status'], 'NOT_HISTORICALLY_CALIBRATED')
        self.assertEqual(engine.health()['snapshot_id'], self.record['snapshot_id'])
        latest = json.loads((engine.root / 'latest.json').read_text())
        latest['created_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        agent_research._atomic_json(engine.root / 'latest.json', latest)
        self.assertEqual(engine.health()['status'], 'STALE')
