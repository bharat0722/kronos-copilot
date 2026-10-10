"""Validation-only real-data challenge; never changes production algorithms."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from tools.run_v3_live_confirmation import load, save, sha, credential, private_check
from app.evidence_snapshot import canonical_bytes

REPORT = ROOT / 'research/results/final_real_world_challenge'
SCOPE = ROOT / 'outputs/final_real_world_challenge'
CANDIDATES = ['HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'AXISBANK', 'LT',
              'BHARTIARTL', 'MARUTI', 'SUNPHARMA', 'BAJFINANCE']
KNOWN = {'RELIANCE', 'TCS', 'IRFC', 'SWIGGY', 'TESTCO'}


def source_hashes():
    paths = [*sorted((ROOT / 'app').glob('*.py')), *sorted((ROOT / 'app').glob('*.js')),
             *sorted((ROOT / 'app').glob('*.css')), *sorted((ROOT / 'app').glob('*.html')),
             ROOT / 'src/first_forecast.py', ROOT / 'src/forecast_config.py',
             *[ROOT / ('research/' + name + '.py') for name in
               ('baselines', 'metrics', 'technical_intelligence', 'market_data', 'market_data_service')]]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def assert_sources():
    expected = load(REPORT / 'selection_plan.json')['source_hashes']
    assert all(sha(ROOT / p) == digest for p, digest in expected.items()), 'Production source changed'


def scan():
    from app import agent_research as ar, agent_output_v4 as v4
    import forecast_config as fc
    from datetime import datetime, timezone
    assert not (REPORT / 'selection_plan.json').exists(), 'Selection already frozen'
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'monad-metropolis'
    prior = load(ROOT / 'research/results/healthcheck_postrepair/v4_final_dual_confirmation.json')
    assert prior['status'] == 'PASS'
    evidence = {s: ['explicit exclusion'] for s in KNOWN}
    folders = [ROOT / 'research/tests', ROOT / 'outputs/agent_research']
    folders += [ROOT / 'research/results' / name for name in
                ('reports', 'healthcheck', 'healthcheck_postrepair', 'agent_audit', 'architecture_audit')]
    scanned = 0
    for folder in folders:
        if not folder.exists():
            continue
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.suffix not in {'.json', '.jsonl', '.md', '.py'}:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if any(x in rel.lower() for x in ('locked', 'protected_target', 'node_modules', '__pycache__')):
                continue
            text = p.read_text(encoding='utf-8-sig', errors='replace')
            found = set(re.findall(r'\b([A-Z][A-Z0-9&-]{1,19})\.NS\b', text))
            found |= {s for s in CANDIDATES if re.search(r'\b' + re.escape(s) + r'\b', text)}
            for symbol in sorted(found):
                evidence.setdefault(symbol, []).append(rel)
            scanned += 1
    eligible = [s for s in CANDIDATES if s not in evidence]
    plan = {'schema_version': 'real_world_black_box_plan_v1',
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'branch': 'monad-metropolis',
            'candidate_universe': CANDIDATES, 'eligible_candidates': eligible,
            'excluded_symbols': evidence, 'historical_files_scanned': scanned,
            'excluded_path_policy': 'No locked/protected targets, datasets, phase1d runs, benchmark artifacts or target contents read',
            'volatility_rule': 'Population standard deviation of log close-to-close returns within each of the latest five fully completed sessions; exclude overnight returns',
            'selection_test1': 'Maximum realized volatility; alphabetical tie break',
            'selection_test2': 'Among candidates other than Test1, closest to median volatility of all eligible candidates; alphabetical tie break',
            'cutoff_rule': 'Latest three completed session-final timestamps with 400 preceding context bars and 75 next-session bars; timestamps/counts only, no target values',
            'primary_horizon': fc.FORECAST_BARS, 'additional_horizons': [24],
            'forecast_config': {'model': 'NeoQuasar/Kronos-base', 'context': fc.LOOKBACK_BARS,
                'horizon': fc.FORECAST_BARS, 'temperature': fc.DEFAULT_TEMPERATURE,
                'top_k': fc.DEFAULT_TOP_K, 'top_p': fc.DEFAULT_TOP_P, 'sample_count': fc.DEFAULT_SAMPLE_COUNT},
            'agent_config': asdict(ar.AgentConfig()), 'schema': v4.SCHEMA_VERSION,
            'validator': v4.VALIDATOR_VERSION, 'prompts': v4.PROMPT_VERSIONS,
            'news_test2': 'EXCLUDED_FOR_LEAKAGE_PREVENTION',
            'budget_policy': 'Unchanged production daily guard, one shared task AgentTeam root, 12 calls/day; each agent at most one retry; stop truthfully if guard blocks later work',
            'baseline_policy': 'Existing persistence/simple_drift/simple_momentum defaults; comparison wins use strict lower 75-bar MAE',
            'source_hashes': source_hashes(), 'production_changes': 0}
    save(REPORT / 'selection_plan.json', plan)
    print(json.dumps({'eligible': eligible, 'excluded': sorted(evidence), 'files_scanned': scanned}, indent=2))


def freeze_blind():
    import pandas as pd
    import forecast_config as fc
    assert_sources()
    assert not (REPORT / 'blind_windows.json').exists(), 'Blind cutoffs already frozen'
    selection = load(REPORT / 'candidate_selection.json')
    symbol = selection['test2_symbol']
    bars = pd.read_csv(SCOPE / (symbol + '.csv'))
    stamps = pd.to_datetime(bars['timestamp'])
    eligible, excluded = [], []
    for day in sorted(set(stamps.dt.date)):
        index = int(stamps[stamps.dt.date == day].index[-1])
        if index + 1 < 400 or len(stamps) - index - 1 < fc.FORECAST_BARS:
            continue
        projected = fc.build_forecast_timestamps(stamps.iloc[index], fc.FORECAST_BARS)
        future_stamps = stamps.iloc[index + 1:]
        present = projected.isin(future_stamps)
        if projected.iloc[-1] not in set(future_stamps):
            excluded.append({'cutoff': stamps.iloc[index].isoformat(), 'reason': 'Production forecast endpoint absent in source timestamps'})
            continue
        eligible.append({'cutoff_index': index, 'cutoff': stamps.iloc[index].isoformat(),
                         'forecast_endpoint': projected.iloc[-1].isoformat(),
                         'horizon_bars': fc.FORECAST_BARS, 'aligned_source_bars': int(present.sum()),
                         'missing_source_timestamps': [x.isoformat() for x in projected[~present]],
                         'context_bars': 400})
    windows = eligible[-3:]
    assert len(windows) == 3, 'Not three timestamp-eligible windows'
    for n, row in enumerate(windows, 1):
        folder = SCOPE / ('window' + str(n))
        folder.mkdir(parents=True, exist_ok=True)
        visible = bars.iloc[row['cutoff_index'] - 399:row['cutoff_index'] + 1].copy()
        visible = visible.rename(columns={'timestamp': 'timestamps'})
        visible = visible[['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']]
        visible.to_csv(folder / 'visible.csv', index=False)
        # The forecast worker never receives the source CSV or this sealed file.
        targets = bars[stamps > pd.Timestamp(row['cutoff'])].copy()
        targets.to_csv(folder / 'sealed_future.csv', index=False)
        row.update(window=n, visible_sha256=sha(folder / 'visible.csv'),
                   sealed_future_sha256=sha(folder / 'sealed_future.csv'),
                   visible_path=(folder / 'visible.csv').relative_to(ROOT).as_posix())
    save(REPORT / 'blind_windows.json', {'status': 'FROZEN_BEFORE_INFERENCE', 'symbol': symbol,
        'windows': windows, 'timestamp_only_eligibility_exclusions': excluded,
        'selection_fields': ['timestamp', 'row_count'], 'outcome_values_inspected_for_cutoffs': False,
        'coverage_policy': 'No interpolation or invented bars; existing timestamp-aligned metrics on observed bars. Require actual production endpoint. Report coverage explicitly.',
        'news': 'NOT_USED_LEAKAGE_PREVENTION', 'source_sha256': sha(SCOPE / (symbol + '.csv'))})
    print(json.dumps({'symbol': symbol, 'windows': windows}, indent=2))


def acquire():
    import numpy as np
    import pandas as pd
    from research.market_data import MarketDataRequest
    from research.market_data_service import MarketDataService, MarketDataError
    assert_sources()
    plan = load(REPORT / 'selection_plan.json')
    assert len(plan['eligible_candidates']) >= 2, 'Fewer than two unseen candidates'
    assert not (REPORT / 'candidate_selection.json').exists(), 'Candidate acquisition already recorded'
    now = pd.Timestamp.now(tz='Asia/Kolkata')
    service = MarketDataService()
    rows = []
    calls = {'market_data_calls': 0, 'openai_calls': 0, 'tavily_calls': 0, 'kronos_inference_runs': 0}
    save(SCOPE / 'calls.json', calls)
    for symbol in plan['eligible_candidates']:
        calls['market_data_calls'] += 1
        save(SCOPE / 'calls.json', calls)
        try:
            result = service.get_bars(MarketDataRequest(symbol, 'NSE'))
            bars = result.bars.copy()
            dates = pd.to_datetime(bars['timestamp']).dt.date
            complete = sorted(d for d in set(dates) if d < now.date() or
                              (d == now.date() and now.hour * 60 + now.minute >= 930))
            bars = bars[dates.isin(complete)].reset_index(drop=True)
            bars.to_csv(SCOPE / (symbol + '.csv'), index=False)
            save(SCOPE / (symbol + '_provenance.json'), result.as_manifest())
            if result.raw_payload:
                (SCOPE / (symbol + '_bronze.csv')).write_text(result.raw_payload, encoding='utf-8')
            selected = bars[pd.to_datetime(bars['timestamp']).dt.date.isin(complete[-5:])]
            returns = selected.groupby(pd.to_datetime(selected['timestamp']).dt.date)['close'].transform(lambda x: np.log(x).diff()).dropna()
            volatility = float(returns.std(ddof=0))
            rows.append({'symbol': symbol, 'volatility': volatility, 'returns_count': len(returns),
                         'sessions': [str(d) for d in complete[-5:]], 'rows': len(bars),
                         'latest_market_timestamp': str(bars['timestamp'].iloc[-1]),
                         'retrieved_at': result.provenance['retrieved_at'], 'quality': result.quality,
                         'market_csv_sha256': sha(SCOPE / (symbol + '.csv')), 'eligible': len(bars) >= 625})
        except MarketDataError as error:
            rows.append({'symbol': symbol, 'eligible': False, 'error': error.as_dict()})
        save(REPORT / 'candidate_acquisition.json', {'candidates': rows, 'calls': calls})
    valid = [r for r in rows if r['eligible']]
    selection = {'candidates': rows, 'status': 'PASS' if len(valid) >= 2 else 'BLOCKED',
                 'market_status': 'CLOSED' if now.weekday() >= 5 or not (555 <= now.hour * 60 + now.minute < 930) else 'OPEN',
                 'checked_at': now.isoformat(), 'market_calendar_basis': 'Existing production weekday/session clock; latest actually returned completed session recorded, no claim of holiday-aware exchange calendar',
                 'market_data_calls': calls['market_data_calls']}
    if len(valid) >= 2:
        first = sorted(valid, key=lambda r: (-r['volatility'], r['symbol']))[0]
        median = float(np.median([r['volatility'] for r in valid]))
        second = sorted([r for r in valid if r['symbol'] != first['symbol']], key=lambda r: (abs(r['volatility'] - median), r['symbol']))[0]
        selection.update(test1_symbol=first['symbol'], test2_symbol=second['symbol'], median_volatility=median)
    save(REPORT / 'candidate_selection.json', selection)
    print(json.dumps(selection, indent=2))


def production_runtime(folder):
    sys.path.insert(0, str(ROOT / 'app'))
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import first_forecast as ff
    import forecast_config as fc
    from app import server
    from app.product_pipeline import ProductPipeline
    from app.news_intelligence import NewsService
    folder.mkdir(parents=True, exist_ok=True)
    # Only output destinations are isolated; model and algorithm settings are untouched.
    ff.OUTPUTS_DIR = folder
    server.SUMMARY_PATH = folder / 'forecast_summary.json'
    server.FORECAST_PATH = folder / 'forecast.csv'
    server.UPLOADED_DATA_PATH = folder / 'input.csv'
    server.FORECAST_CACHE_DIR = SCOPE / 'forecast_cache'
    server.PRODUCT_PIPELINE = ProductPipeline(folder / 'pipeline')
    server.NEWS_SERVICE = NewsService(SCOPE / 'news_cache')
    server.EVIDENCE_DIR = folder / 'evidence_snapshots'
    expected = load(REPORT / 'selection_plan.json')['forecast_config']
    actual = {'model': ff.MODEL_NAME, 'context': fc.LOOKBACK_BARS, 'horizon': fc.resolve_forecast_bars(None),
              'temperature': float(os.environ.get('KRONOS_T', fc.DEFAULT_TEMPERATURE)),
              'top_k': int(os.environ.get('KRONOS_TOP_K', fc.DEFAULT_TOP_K)),
              'top_p': float(os.environ.get('KRONOS_TOP_P', fc.DEFAULT_TOP_P)),
              'sample_count': int(os.environ.get('KRONOS_SAMPLE_COUNT', fc.DEFAULT_SAMPLE_COUNT))}
    assert actual == expected, 'Production configuration differs from frozen plan'
    return server


def count(name):
    state = load(SCOPE / 'calls.json')
    state[name] = state.get(name, 0) + 1
    save(SCOPE / 'calls.json', state)


def agent_workflow(label, folder, record, pipeline, as_of=None, retrieval_only=False):
    from app import agent_research as ar, agent_output_v4 as v4
    from app.evidence_fusion import EvidenceFusionEngine
    from tools.run_v3_live_confirmation import AllowedTransport
    import httpx2 as httpx
    from openai import OpenAI
    assert_sources()
    credential()
    config = ar.AgentConfig()
    plan = load(REPORT / 'selection_plan.json')
    assert asdict(config) == plan['agent_config']
    assert ar.SCHEMA_VERSION == 'agent_output_v4' and ar.PROMPT_VERSIONS == plan['prompts']
    root = SCOPE / 'agents'
    def no_provider():
        raise RuntimeError('Read-only retrieval cannot call provider')
    reader = ar.AgentTeam(root, config=config, client_factory=no_provider)
    preflight = reader.preflight(record)
    before = reader.result(record)
    if not retrieval_only:
        assert all(not e.get('report') for e in before['agents'].values()), 'Old accepted cache entry'
    raw = ar.evidence_catalog(record['evidence'])
    wire = v4.serialize(record, raw)
    private_check(json.loads(wire))
    if not retrieval_only:
        save(folder / 'agent_preflight.json', {'preflight': preflight, 'input_sha256': hashlib.sha256(wire).hexdigest(),
             'input_bytes': len(wire), 'initial_cache_miss': {r: True for r in ar.AGENTS}, 'catalogue': v4.catalogue(raw)})
    transport = AllowedTransport()
    http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.openai.com/v1',
                    timeout=config.timeout_seconds, max_retries=0, http_client=http)
    class Responses:
        role_calls = {r: 0 for r in ar.AGENTS}
        def create(self, **request):
            assert_sources()
            state = load(SCOPE / 'calls.json')
            assert state['openai_calls'] < 12, 'Unchanged shared daily budget exhausted'
            role = request['text']['format']['schema']['properties']['agent_type']['enum'][0]
            assert self.role_calls[role] < 2
            assert request['instructions'] == v4.instructions(role, v4.PROMPT_VERSIONS[role])
            assert request['model'] == config.model and request['max_output_tokens'] == 1600
            assert request['tools'] == [] and request['tool_choice'] == 'none'
            assert request['input'].split('\n', 1)[1].encode() == wire
            self.role_calls[role] += 1
            count('openai_calls')
            print(f'{label} live {role} attempt {self.role_calls[role]}', flush=True)
            return client.responses.create(**request)
    guarded = type('GuardedClient', (), {'responses': Responses()})()
    team = ar.AgentTeam(root, config=config, client_factory=lambda: guarded)
    engine = EvidenceFusionEngine(folder / 'fusion')
    pre_agent_input = {**before, 'agents': {}, 'agents_completed': 0} if retrieval_only else before
    pre_agent = engine.fuse(record, agent_result=pre_agent_input, pipeline=pipeline, as_of=as_of)
    immutable = canonical_bytes(record)
    try:
        result = before if retrieval_only else team.run(record)
    finally:
        client.close()
        if not retrieval_only:
            save(folder / 'transport.json', {'openai_requests': transport.requests})
    cached = reader.result(record)
    fusion = engine.fuse(record, agent_result=cached, pipeline=pipeline, as_of=as_of)
    hit = engine.fuse(record, agent_result=cached, pipeline=pipeline, as_of=as_of)
    attempts = [load(p) for p in sorted((root / 'attempts').glob('*.json')) if load(p).get('snapshot_id') == record['snapshot_id']]
    runs = [load(p) for p in sorted((root / 'runs').glob('*.json')) if load(p).get('snapshot_id') == record['snapshot_id']]
    audit = {}
    catalogue = v4.catalogue(raw)
    for role, entry in cached['agents'].items():
        report = entry.get('report')
        if not report:
            audit[role] = {'status': entry.get('status'), 'error': entry.get('error')}
            continue
        built = v4.build_result(report, role, record['snapshot_id'], raw)
        audit[role] = {**built, 'available_evidence_ids': sorted(catalogue),
                      'role_admissibility_proof': [{**catalogue[e['evidence_id']],
                        'selected_use': e['use'], 'admissible': e['use'] in catalogue[e['evidence_id']]['role_compatibility'][role]}
                       for e in report['selected_evidence']]}
    agent_items = [e for e in fusion['evidence_items'] if e['evidence_type'].startswith('AGENT_')]
    checks = {'team_3of3': cached['agents_completed'] == 3,
        'durable': cached['team_status'] == result['team_status'] and cached['snapshot_id'] == record['snapshot_id'],
        'immutability': immutable == canonical_bytes(record),
        'structured_grounding': len(audit) == 3 and all('resolved_facts' in x for x in audit.values()),
        'no_double_counting': all(e['role'] == 'DERIVED' and not e['contributes_to_direction'] for e in agent_items),
        'agent_fusion': len(agent_items) == 3,
        'fusion_cache_refresh': fusion['result_hash'] != pre_agent['result_hash'] if cached['agents_completed'] else True,
        'fusion_cache_hit': hit['cache_status'] == 'hit',
        'ledger': len(runs) == 3 and bool(attempts),
        'dashboard_adapter': all(e.get('presentation', {}).get('schema_version') == 'agent_output_v4' for e in cached['agents'].values()),
        'no_truncation': all(a.get('completion_reason') != 'max_output_tokens' for a in attempts),
        'snapshot_identity': fusion['snapshot_id'] == record['snapshot_id']}
    out = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks, 'team': result,
        'cached_team': cached, 'agent_audit': audit, 'fusion': fusion, 'health': team.health(record),
        'fusion_health': engine.health(), 'attempt_records': attempts, 'ledger_records': runs,
        'snapshot_id': record['snapshot_id'], 'serialized_size': len(wire), 'api_cost': 'UNKNOWN'}
    private_check(out)
    save(folder / 'agent_integration.json', out)
    return out


def test1(retrieval_only=False):
    import pandas as pd
    assert_sources()
    folder = SCOPE / 'test1'
    if not retrieval_only:
        assert not (folder / 'started.json').exists(), 'Test1 already started; no rerun'
    selection = load(REPORT / 'candidate_selection.json')
    symbol = selection['test1_symbol']
    server = production_runtime(folder)
    if retrieval_only:
        dashboard = load(folder / 'dashboard.json')
        news = load(folder / 'news.json')
    else:
        save(folder / 'started.json', {'symbol': symbol, 'started_at': pd.Timestamp.now(tz='UTC').isoformat()})
        count('market_data_calls')
        count('kronos_inference_runs')
        print('Test1 production forecast starting: ' + symbol, flush=True)
        dashboard = server.fetch_live_forecast(symbol, 'NSE')
        save(folder / 'dashboard.json', dashboard)
        print('Test1 forecast completed; production news next', flush=True)
        news = server.build_news_research_payload(symbol + '.NS', refresh=True)
        save(folder / 'news.json', news)
        state = load(SCOPE / 'calls.json')
        state['tavily_calls'] = server.NEWS_SERVICE.tavily_provider.requests
        save(SCOPE / 'calls.json', state)
    digest = news.get('evidence_snapshot_id')
    assert digest, 'Production news join did not create a matching snapshot'
    from app.evidence_snapshot import read_snapshot
    record = read_snapshot(server.EVIDENCE_DIR, digest)
    pipeline = server.PRODUCT_PIPELINE.snapshot()
    out = agent_workflow('Test1', folder, record, pipeline, retrieval_only=retrieval_only)
    pipeline['stages']['news'] = server.NEWS_SERVICE.pipeline_stage()
    pipeline['stages']['agents'] = out['health']
    pipeline['stages']['fusion'] = out['fusion_health']
    out.update(symbol=symbol, previously_used=False, market_status=selection['market_status'],
        latest_market_timestamp=dashboard['timing']['last_yahoo_market_bar'], dashboard=dashboard,
        news=news, pipeline=pipeline, record=record,
        market_provenance=load(folder / 'pipeline/latest.json')['provenance'],
        why_selected='Highest pre-frozen five-session realized volatility among unseen candidates')
    save(REPORT / 'test1_live_stress.json', out)
    if retrieval_only:
        save(REPORT / 'validation_runner_incident.json', {'category': 'REPORT_COLLECTOR',
             'reason': 'Collector requested category; production EvidenceItem uses evidence_type',
             'recovered_from_saved_state': True, 'additional_provider_calls': 0,
             'production_code_changes': 0})
    print(json.dumps({'test1_status': out['status'], 'team': out['team']['agents_completed'],
                      'fusion': out['fusion']['view'], 'news': news['status'], 'calls': load(SCOPE / 'calls.json')}, indent=2), flush=True)


def recover_test1():
    test1(retrieval_only=True)


def window(number):
    import pandas as pd
    from research.market_data import MarketDataRequest, ProviderResult, normalize_provider_bars, provider_quality_contract
    from research.baselines import BASELINES
    from app.evidence_snapshot import create_content, save_snapshot
    from app.news_impact import assess_news, research_outlook
    assert_sources()
    manifest = load(REPORT / 'blind_windows.json')
    row = manifest['windows'][number - 1]
    symbol = manifest['symbol']
    folder = SCOPE / ('window' + str(number))
    assert not (folder / 'started.json').exists(), 'Window already started; no rerun'
    assert sha(folder / 'visible.csv') == row['visible_sha256']
    visible = pd.read_csv(folder / 'visible.csv')
    visible['timestamps'] = pd.to_datetime(visible['timestamps'])
    cutoff = pd.Timestamp(row['cutoff'])
    assert len(visible) == 400 and visible['timestamps'].max() == cutoff
    assert (visible['timestamps'] <= cutoff).all()
    server = production_runtime(folder)
    acquisition = load(SCOPE / (symbol + '_provenance.json'))['provenance']
    request = MarketDataRequest(symbol, 'NSE')
    canonical = normalize_provider_bars(visible.rename(columns={'timestamps': 'timestamp'}),
        provider='yahoo', request=request, retrieved_at=acquisition['retrieved_at'])
    quality = provider_quality_contract(canonical, request=request, provider='yahoo', retrieved_at=acquisition['retrieved_at'])
    provenance = {**acquisition, 'source_symbol': symbol + '.NS', 'as_of_cutoff': cutoff.isoformat(),
                  'visible_context_sha256': row['visible_sha256'], 'filter': 'timestamp <= cutoff',
                  'challenge_mode': 'historical_blind_online_history'}
    result = ProviderResult('yahoo', request, canonical, provenance, quality,
        {'status': 'HEALTHY' if quality['state'] == 'PASS' else 'DEGRADED'}, visible.to_csv(index=False))
    capture_id = server.PRODUCT_PIPELINE.capture(result)
    save(folder / 'started.json', {'window': number, 'cutoff': cutoff.isoformat(),
         'worker_inputs': [row['visible_path'], 'configuration and timestamp-only manifest'],
         'sealed_future_opened': False, 'started_at': pd.Timestamp.now(tz='UTC').isoformat()})
    print(f'Blind window {number}: production Kronos on visible context only', flush=True)
    count('kronos_inference_runs')
    dashboard = server.run_forecast(visible.to_csv(index=False), symbol + '.NS live 5-minute data')
    server.PRODUCT_PIPELINE.complete(capture_id, visible, dashboard)
    summary = load(folder / 'forecast_summary.json')
    fingerprint = server.summary_fingerprint(summary)
    technicals = server.PRODUCT_PIPELINE.matching_technicals(symbol + '.NS', fingerprint)
    assert technicals and pd.Timestamp(technicals['as_of']) <= cutoff
    news = {'symbol': symbol + '.NS', 'status': 'UNAVAILABLE', 'provider': 'EXCLUDED_FOR_LEAKAGE_PREVENTION',
            'events': [], 'retrieved_at': None, 'cache_status': 'not_applicable'}
    impact = assess_news(news, '')
    outlook = research_outlook(str(summary['direction']), technicals, impact, model_as_of=technicals['as_of'],
        forecast_ends_at=row['forecast_endpoint'], as_of=cutoff.to_pydatetime())
    market = load(folder / 'pipeline/latest.json')
    content = create_content(symbol=symbol + '.NS', exchange='NSE', summary=summary, fingerprint=fingerprint,
        forecast_sha256=sha(folder / 'forecast.csv'), input_sha256=sha(folder / 'input.csv'),
        market=market, technicals=technicals, news=news, impact=impact, outlook=outlook,
        technical_version=technicals['analysis_version'])
    record = save_snapshot(server.EVIDENCE_DIR, content)
    pipeline = server.PRODUCT_PIPELINE.snapshot()
    out = agent_workflow('Window' + str(number), folder, record, pipeline, as_of=cutoff.to_pydatetime())
    predicted = pd.read_csv(folder / 'forecast.csv').rename(columns={'timestamps': 'timestamp'})
    predicted['timestamp'] = pd.to_datetime(predicted['timestamp'])
    context = visible.rename(columns={'timestamps': 'timestamp'})
    baseline_hashes = {}
    for name, method in BASELINES.items():
        data = method(context, predicted['timestamp'])
        path = folder / (name + '_prediction.csv')
        data.to_csv(path, index=False)
        baseline_hashes[name] = sha(path)
    frozen = {'window': number, 'symbol': symbol, 'cutoff': cutoff.isoformat(),
        'news': 'NOT_USED_LEAKAGE_PREVENTION', 'snapshot_id': record['snapshot_id'],
        'forecast_sha256': sha(folder / 'forecast.csv'), 'context_sha256': row['visible_sha256'],
        'baseline_sha256': baseline_hashes, 'agent_result_sha256': sha(folder / 'agent_integration.json'),
        'fusion_view_before_reveal': out['fusion']['view'], 'fusion_result_hash': out['fusion']['result_hash'],
        'predictions_persisted_at': pd.Timestamp.now(tz='UTC').isoformat(),
        'sealed_future_opened': False, 'model_configuration': load(REPORT / 'selection_plan.json')['forecast_config']}
    frozen['freeze_hash'] = hashlib.sha256(canonical_bytes(frozen)).hexdigest()
    save(folder / 'frozen_prediction.json', frozen)
    print(json.dumps({'window': number, 'team': out['team']['agents_completed'], 'fusion': out['fusion']['view'],
                      'freeze_hash': frozen['freeze_hash'], 'future_revealed': False}), flush=True)


def score(number):
    import pandas as pd
    from research.metrics import close_metrics
    assert_sources()
    folder = SCOPE / ('window' + str(number))
    assert not (folder / 'scores.json').exists(), 'Outcome already scored; no replacement'
    frozen = load(folder / 'frozen_prediction.json')
    assert hashlib.sha256(canonical_bytes({k: v for k, v in frozen.items() if k != 'freeze_hash'})).hexdigest() == frozen['freeze_hash']
    row = load(REPORT / 'blind_windows.json')['windows'][number - 1]
    assert sha(folder / 'sealed_future.csv') == row['sealed_future_sha256']
    assert sha(folder / 'forecast.csv') == frozen['forecast_sha256']
    assert sha(folder / 'agent_integration.json') == frozen['agent_result_sha256']
    assert sha(folder / 'visible.csv') == frozen['context_sha256']
    # This is the first scoring-stage read of target values, after the forecast worker exits.
    actual = pd.read_csv(folder / 'sealed_future.csv')
    actual['timestamp'] = pd.to_datetime(actual['timestamp'])
    context = pd.read_csv(folder / 'visible.csv').rename(columns={'timestamps': 'timestamp'})
    context['timestamp'] = pd.to_datetime(context['timestamp'])
    predicted = pd.read_csv(folder / 'forecast.csv').rename(columns={'timestamps': 'timestamp'})
    predicted['timestamp'] = pd.to_datetime(predicted['timestamp'])
    metrics = {}
    predictions = {'kronos': predicted}
    for name, digest in frozen['baseline_sha256'].items():
        path = folder / (name + '_prediction.csv')
        assert sha(path) == digest
        data = pd.read_csv(path)
        data['timestamp'] = pd.to_datetime(data['timestamp'])
        predictions[name] = data
    for horizon in (24, 75):
        metrics[str(horizon)] = {name: close_metrics(data.head(horizon), actual, context) for name, data in predictions.items()}
    main = metrics['75']['kronos']
    assert main['compared_bars'] == row['aligned_source_bars']
    view = frozen['fusion_view_before_reveal']
    sign = 'up' if view in {'BULLISH', 'STRONGLY_BULLISH'} else 'down' if view in {'BEARISH', 'STRONGLY_BEARISH'} else None
    out = {'window': number, 'cutoff': frozen['cutoff'], 'metrics': metrics,
        'production_horizon': 75, 'observed_horizon_coverage': main['compared_bars'],
        'fusion_view_before_reveal': view, 'fusion_directional_match': sign == main['actual_direction'] if sign else None,
        'freeze_hash': frozen['freeze_hash'], 'prediction_frozen_at': frozen['predictions_persisted_at'],
        'revealed_at': pd.Timestamp.now(tz='UTC').isoformat(), 'no_future_leakage': True,
        'extended_120': 'UNAVAILABLE_FROM_DEFAULT_75_BAR_FORECAST_NO_RERUN'}
    save(folder / 'scores.json', out)
    print(json.dumps({'window': number, 'primary_metrics': main, 'fusion': view, 'fusion_match': out['fusion_directional_match']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['scan', 'acquire', 'freeze_blind', 'test1', 'recover_test1', 'window', 'score'])
    parser.add_argument('--number', type=int, choices=[1, 2, 3])
    args = parser.parse_args()
    if args.stage in {'window', 'score'}:
        assert args.number is not None
        globals()[args.stage](args.number)
    else:
        globals()[args.stage]()
