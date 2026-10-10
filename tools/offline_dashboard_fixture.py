"""Create public-safe browser QA evidence without inference or external calls."""
from __future__ import annotations
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'src')]

def main():
    import pandas as pd
    from app import server
    from app.agent_research import AgentTeam
    from app.evidence_fusion import EvidenceFusionEngine
    from app.evidence_snapshot import read_snapshot
    from app.product_pipeline import ProductPipeline
    from first_forecast import build_summary, FEATURES
    from research.market_data import MarketDataRequest, ProviderResult
    from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'}):
        root = Path(directory)
        stamp = datetime.now(timezone.utc).isoformat()
        times = pd.date_range('2026-10-08 09:15', periods=400, freq='5min', tz='Asia/Kolkata')
        history = pd.DataFrame({'timestamps': times, **{feature: [100.0] * 400 for feature in FEATURES}})
        history['high'], history['low'] = 101.0, 99.0
        future = pd.DataFrame({'timestamps': pd.date_range(times[-1] + pd.Timedelta(minutes=5), periods=75, freq='5min'),
                               **{feature: [100.0] * 75 for feature in FEATURES}})
        future['high'], future['low'] = 101.0, 99.0
        summary = build_summary(history, future, 'TESTCO.NS live 5-minute data', forecast_bars=75,
            temperature=1.0, top_k=0, top_p=0.9, sample_count=1, inference_seconds=0.0)
        (root / 'summary.json').write_text(json.dumps(summary))
        history.to_csv(root / 'history.csv', index=False)
        future.to_csv(root / 'forecast.csv', index=False)
        pipeline = ProductPipeline(root / 'pipeline')
        captured = pipeline.capture(ProviderResult(provider='synthetic', request=MarketDataRequest('TESTCO.NS'),
            bars=history.rename(columns={'timestamps': 'timestamp'}), provenance={'retrieved_at': stamp, 'source_symbol': 'TESTCO.NS'},
            quality={'state': 'PASS', 'issues': []}, health={'status': 'HEALTHY'}, raw_payload='Synthetic QA fixture'))
        patches = {'SUMMARY_PATH': root / 'summary.json', 'UPLOADED_DATA_PATH': root / 'history.csv',
                   'FORECAST_PATH': root / 'forecast.csv', 'EVIDENCE_DIR': root / 'evidence',
                   'PRODUCT_PIPELINE': pipeline}
        from contextlib import ExitStack
        with ExitStack() as stack:
            for key, value in patches.items():
                stack.enter_context(patch.object(server, key, value))
            dashboard = server.build_dashboard_payload(summary)
            pipeline.complete(captured, history, dashboard)
            dashboard = server.build_dashboard_payload(summary)
            news_raw = {'symbol': 'TESTCO.NS', 'status': 'NO_EVIDENCE', 'events': [], 'provider': 'synthetic',
                        'retrieved_at': stamp, 'cache_status': 'miss', 'providers_used': [],
                        'message': 'No verified recent evidence.', 'news_pipeline': {'silver_rows': 0}}
            stack.enter_context(patch.object(server, 'NEWS_SERVICE', SimpleNamespace(get=lambda *args, **kwargs: news_raw,
                                                        cache_dir=root / 'news',
                                                        official_name=lambda symbol: 'Synthetic TESTCO',
                                                        record_impact=lambda value: None)))
            news = server.build_news_research_payload('TESTCO.NS', company_hint='Synthetic TESTCO')
            record = read_snapshot(root / 'evidence', news['evidence_snapshot_id'])
            teams = {}
            fusions = {}
            for state, failing in [('COMPLETE', ()), ('PARTIAL', ('risk',)), ('FAILED', ('bull', 'bear', 'risk'))]:
                client = MockClient(lambda role: mock_response(role, record['snapshot_id'], status='incomplete',
                    incomplete_reason='max_output_tokens') if role in failing else mock_response(role, record['snapshot_id']))
                team = AgentTeam(root / state, client_factory=lambda: client)
                result = team.run(record)
                teams[state] = team.result(record)
                engine = EvidenceFusionEngine(root / (state + '_fusion'))
                fusions[state] = engine.fuse(record, agent_result=teams[state], pipeline=pipeline.snapshot())
            payload = {'dashboard': dashboard, 'news': news, 'teams': teams, 'fusions': fusions,
                       'pipeline': pipeline.snapshot(), 'fixture_only': True}
            Path(sys.argv[1]).write_text(json.dumps(payload), encoding='utf-8')

if __name__ == '__main__':
    main()
