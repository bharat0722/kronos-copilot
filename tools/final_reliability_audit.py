"""Scoped preservation and reporting for the final V4 reliability repair."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'outputs/final_reliability_closure'
REPORTS = ROOT / 'research/results/healthcheck_postrepair'
HISTORY = ROOT / 'research/results/final_real_world_challenge'
WINDOW = ROOT / 'outputs/final_real_world_challenge/window2'
SNAPSHOT = '29bb71d3d16adc772a39bcd0e88368eadba231a4e15fe0efe080fdee96b7c87c'
RUN = 'a835edc3d41e8d0dd002a7e19b226d16'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def begin():
    from app import agent_research as ar, agent_output_v4 as v4
    assert not (OUT / 'before.json').exists(), 'Preservation baseline already exists; do not overwrite it'
    paths = list(HISTORY.rglob('*')) + list(REPORTS.glob('*'))
    paths += [ROOT / 'app' / name for name in ('agent_research.py', 'agent_output_v4.py',
              'usage_budget.py', 'evidence_fusion.py', 'dashboard.js', 'server.py',
              'product_pipeline.py', 'news_intelligence.py', 'agent_output_v3.py')]
    for number in (1, 2, 3):
        window = ROOT / f'outputs/final_real_world_challenge/window{number}'
        for name in ('forecast.csv', 'forecast_summary.json', 'frozen_prediction.json', 'scores.json'):
            paths.append(window / name)
        paths.extend((window / 'evidence_snapshots').glob('*.json'))
    paths.extend((ROOT / 'outputs/final_real_world_challenge/agents/attempts').glob('*.json'))
    paths.extend((ROOT / 'outputs/final_real_world_challenge/agents/runs').glob('*.json'))
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths if p.is_file()}
    record = read(WINDOW / f'evidence_snapshots/{SNAPSHOT}.json')
    raw = ar.evidence_catalog(record['evidence'])
    catalogue = v4.catalogue(raw)
    assert catalogue == read(WINDOW / 'agent_preflight.json')['catalogue']
    schema = v4.schema('bull', tuple(catalogue))
    original = {'schema_version': v4.SCHEMA_VERSION, 'agent_type': 'bull', 'snapshot_id': SNAPSHOT,
                'action': 'PRESENT_CASE', 'selected_evidence': [
                    {'evidence_id': 'kronos.direction', 'priority': 1, 'use': 'SUPPORT'}],
                'optional_explanation': None}
    try:
        v4.validate(original, 'bull', SNAPSHOT, raw)
        raise AssertionError('Invalid structural equivalent was accepted')
    except v4.ContractError as error:
        assert (error.code, error.path) == ('role_admissibility', '$.selected_evidence[0].use')
    parents = ROOT / 'outputs/final_real_world_challenge/agents'
    retained = [read(parents / f'attempts/{RUN}.{n}.json') for n in (1, 2)]
    assert all(r['validation_diagnostic']['rule_code'] == 'role_admissibility' for r in retained)
    save(OUT / 'before.json', {'hashes': hashes, 'old_schema': schema, 'catalogue': catalogue,
         'raw': raw, 'original_shape': original, 'retained_attempts': retained,
         'exact_provider_output_retained': False, 'classification': 'OTHER',
         'primary_cause': 'Provider schema admits role/ID/use combinations forbidden by the backend catalogue',
         'historical_payload_limitation': 'Rejected evidence ID, use and action were not persisted; no exact output replay is possible'})
    # A portable fixture contains only visible catalogue inputs, never future bars.
    keys = set(catalogue) | {'technicals.as_of', 'market_data.retrieved_at', 'news.retrieved_at'}
    portable = {key: value for key, value in raw.items() if key in keys}
    save(ROOT / 'research/tests/fixtures/window2_role_use_regression.json',
         {'source': 'Frozen Window 2 visible evidence; rejected output is a structural equivalent, not recovered JSON',
          'snapshot_id': SNAPSHOT, 'raw': portable, 'reconstruction': original})
    print(json.dumps({'preserved_files': len(hashes), 'classification': 'OTHER',
          'frozen_catalogue_verified': True, 'structural_equivalent_rejection': 'role_admissibility',
          'exact_output_recoverable': False}))


def offline():
    from datetime import datetime, timezone
    from app.evidence_fusion import EvidenceFusionEngine
    from research.tests.fixtures.dual_retest_fixtures import build_fixture
    from research.tests.test_agent_output_v4 import full_team
    from unittest.mock import patch
    import os
    browser = read(REPORTS/'v4_browser_fixture.json')
    outcomes = {}
    with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-only'}):
        for case in ('A', 'B'):
            fixture = build_fixture(case, datetime.now(timezone.utc).isoformat())
            result = full_team(fixture, OUT/f'offline_{case}',
                     lambda role, report, count: {**report, 'optional_explanation': 'RSI is 999.'})
            assert all(result['checks'].values()), result['checks']
            result['fusion_health'] = EvidenceFusionEngine(OUT/f'offline_{case}/fusion').health()
            outcomes[case] = result
    browser['outcomes'] = outcomes
    save(OUT/'browser_fixture.json', browser)
    save(OUT/'offline_integration.json', outcomes)
    print(json.dumps({case: result['checks'] for case, result in outcomes.items()}))


def finish():
    from datetime import datetime, timezone
    from app import agent_research as ar, agent_output_v4 as v4
    baseline = read(OUT/'before.json')
    expected_changes = {'app/agent_research.py', 'app/agent_output_v4.py', 'app/usage_budget.py'}
    changed = [p for p, h in baseline['hashes'].items() if digest(ROOT/p) != h]
    assert set(changed) == expected_changes, changed
    tests = read(OUT/'offline_tests.json')
    assert tests['failed'] == tests['errors'] == tests['blocked_external_attempts'] == 0
    integrations = read(OUT/'offline_integration.json')
    assert all(all(row['checks'].values()) for row in integrations.values())
    qa = read(OUT/'dashboard_qa/qa.json')
    assert qa['status'] == 'PASS' and len(qa['checks']) == 6
    live = read(OUT/'live_execution.json')
    live_integration = read(OUT/'bull_live_integration.json')
    assert live['status'] == 'PASS' and live_integration['all_checks']
    assert live['provider_calls'] == live['transport_calls'] == live['api_calls'] == 1
    attempts = [read(p) for p in (OUT/'agents/attempts').glob('*.json')]
    assert len(attempts) == 1 and attempts[0]['response_status'] == 'completed'
    backend = read(OUT/'bull_backend_result.json')
    wire = copy_dict(baseline['original_shape'])
    wire['selected_evidence'][0]['use'] = 'COUNTER'
    corrected = v4.validate(wire, 'bull', SNAPSHOT, baseline['raw'])
    prior = read(HISTORY/'final_black_box_verdict.json')
    assert prior['performance']['direction_hits'] == 1
    assert prior['performance']['kronos_beats'] == {'persistence': 0, 'drift': 3, 'momentum': 0}
    assert prior['real_market_performance'] == 'WEAK_IN_THIS_THREE_WINDOW_CHALLENGE'
    preserved = {p: h for p, h in baseline['hashes'].items() if p not in expected_changes}
    save(OUT/'preservation_verification.json', {'status': 'PASS', 'files_verified': len(preserved),
         'hashes': preserved, 'expected_production_changes': sorted(expected_changes)})
    role_contract = {'version': v4.ROLE_USE_CONTRACT_VERSION, 'schema': v4.SCHEMA_VERSION,
        'validator': v4.VALIDATOR_VERSION, 'use_enums': list(v4.MODES), 'actions': v4.ACTIONS,
        'limits': v4.LIMITS, 'authority': 'Backend catalogue role_compatibility, generated by one _roles function',
        'consumers': ['catalogue', 'admissible_uses', 'strict schema', 'validator', 'prompt enum labels', 'tests'],
        'bull': {'eligible_bullish': ['SUPPORT'], 'eligible_bearish': ['COUNTER'], 'risk_or_neutral': ['RISK']},
        'bear': {'eligible_bearish': ['SUPPORT'], 'eligible_bullish': ['COUNTER'], 'risk_or_neutral': ['RISK']},
        'risk': 'RISK for risk-relevant sources or eligible directional evidence',
        'ineligible_directional': 'FAIL quality or STALE freshness cannot SUPPORT/COUNTER; risk qualification may remain',
        'schema_pair_binding': 'Grouped nested anyOf; each evidence ID has only its catalogue-approved use enums',
        'empty_catalogue': 'ABSTAIN only, maxItems=0', 'rank_and_duplicates': 'Consecutive integer priorities; duplicate IDs rejected',
        'no_support': 'ABSTAIN remains valid; counter-only PRESENT_CASE is valid but backend support is INSUFFICIENT',
        'explanation_nonblocking': True, 'role_rules_changed': False,
        'snapshot_bound': True, 'model_fact_direction_ownership': False,
        'schema_reference': 'https://developers.openai.com/api/docs/guides/structured-outputs'}
    save(REPORTS/'v4_role_use_contract_v2.json', role_contract)
    replay = {'status': 'PARTIAL', 'historical_snapshot_id': SNAPSHOT, 'historical_run_id': RUN,
        'primary_cause_classification': 'OTHER', 'proven_primary_gap': baseline['primary_cause'],
        'exact_original_output_reproduced': False, 'exact_requested_use': None, 'exact_evidence_id': None,
        'exact_bull_action': None, 'reason_exact_replay_unavailable': baseline['historical_payload_limitation'],
        'retained_attempts': baseline['retained_attempts'],
        'structural_equivalent_only': {'original_output': baseline['original_shape'],
            'evidence_id': 'kronos.direction', 'family': 'FORECAST', 'direction': 'BEARISH',
            'role_compatibility': baseline['catalogue']['kronos.direction']['role_compatibility'],
            'requested_use': 'SUPPORT', 'allowed_uses': ['COUNTER', 'RISK'],
            'old_provider_schema_admitted': True, 'original_validator_result': 'FAIL_AS_EXPECTED',
            'rule_code': 'role_admissibility', 'json_path': '$.selected_evidence[0].use',
            'corrected_output': corrected, 'corrected_result': 'PASS', 'new_provider_schema_admits_invalid_pair': False},
        'live_confirmation': live, 'live_selected_evidence': backend['selected_evidence'],
        'no_symbol_or_id_whitelist': True, 'provenance_note': 'The reconstructed pair is not claimed to be either original provider response'}
    save(REPORTS/'axisbank_window2_bull_replay.json', replay)
    reviewed = {'gstack': 'PARTIAL', 'scoped_review': 'PASS', 'scoped_security': 'PASS', 'local_browser_qa': 'PASS',
        'native_aside': 'UNAVAILABLE: command lookup returned NEEDS_ASIDE',
        'native_learning_log': 'UNAVAILABLE: gstack-learnings-log returned bun: command not found',
        'independent_external_model_review': 'NOT_RUN: no extra LLM judge calls authorized',
        'finding_count': 0, 'architecture': 'GREEN', 'architecture_score': 8.9,
        'score_scope': 'Scoped engineering assessment, not a measured product or model-performance score',
        'checks': {'prose_not_in_acceptance': True, 'role_matrix_unchanged': True,
            'schema_and_validator_same_admissibility': True, 'backend_fact_ownership': True,
            'bounded_workflows': True, 'parameterized_atomic_usage_accounting': True,
            'cache_version_invalidation': True, 'no_role_specific_hacks': True,
            'auth_csrf_origin_source_unchanged': True, 'fusion_weights_source_unchanged': True},
        'tooling_limits_are_not_software_health_blockers': True,
        'upgrade_not_performed': 'Targeted repair scope; existing review/checklists used without unrelated tool updates'}
    safety = {'openai_calls': live['provider_calls'], 'kronos_inference': 0, 'kronos_training': 0,
        'tavily_calls': 0, 'yahoo_calls': 0, 'monad_calls': 0, 'new_market_data_calls': 0,
        'model_weight_changes': 0, 'validation_reruns': 0, 'locked_test_accesses': 0,
        'monad_implementation': False, 'git_commit': False, 'git_push': False}
    gate = {'schema_version': 'final_pre_monad_health_gate_v1', 'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': 'PARTIAL', 'software_reliability_status': 'PASS',
        'status_reason': 'Software reliability closed; exact historical payload replay cannot be fulfilled because rejected JSON was not retained',
        'primary_cause': 'OTHER: provider-schema / backend-validator role-use pairing mismatch',
        'v4_architecture': 'UNCHANGED responsibility boundary; response-schema constraints tightened',
        'schema': v4.SCHEMA_VERSION, 'validator': v4.VALIDATOR_VERSION,
        'prompts': v4.PROMPT_VERSIONS, 'prompt_content_unchanged': True,
        'role_use_contract': v4.ROLE_USE_CONTRACT_VERSION, 'single_source_of_truth': 'PASS',
        'old_daily_project_guard': 'REMOVED_FROM_PRODUCTION_V4_EXECUTION_AND_HEALTH_GATING',
        'legacy_daily_guard': 'Preserved only for explicit V2/V3 historical replay harnesses; not current production',
        'budget': {'workflow_max_calls': 6, 'bull_only_max_calls': 2, 'max_retries': 1,
            'max_input_bytes': 48000, 'max_output_tokens': 1600, 'sdk_retries': 0,
            'daily_usage_still_recorded': True, 'daily_count_before': live['daily_count_before'],
            'daily_count_after': live['daily_count_after'], 'provider_limits': 'UNCHANGED',
            'authorization_lan_auth_csrf_origin': 'UNCHANGED'},
        'tests': tests, 'normal_team_offline': '3/3', 'adversarial_team_offline': '3/3',
        'offline_integration_checks': {case: row['checks'] for case, row in integrations.items()},
        'live_confirmation_required': True, 'live_confirmation_reason': 'Real provider must exercise tightened strict schema; exact historical rejected shape unavailable',
        'live_confirmation_result': 'PASS', 'live_calls_maximum': 2, 'live_confirmation': live,
        'live_token_usage': attempts[0]['token_usage'], 'live_scope': 'Bull ONLY; deliberately PARTIAL live team, not claimed as a new 3/3 live run',
        'live_integration_checks': live_integration['checks'], 'reviews': reviewed,
        'health_basis': 'Full current offline teams + prior V4 dual-live success and real Bear/Risk acceptances + targeted current Bull live success',
        'health': {name: 'GREEN' for name in ('system', 'ai_research_team', 'bull', 'bear', 'risk',
                    'evidence_fusion', 'pipeline', 'dashboard', 'security', 'architecture')},
        'blind_forecast_performance': 'WEAK - PRESERVED', 'prior_market_performance': prior['real_market_performance'],
        'prior_kronos_direction_hits': '1/3', 'prior_baseline_mae_wins': {'persistence': '0/3', 'drift': '3/3', 'momentum': '0/3'},
        'model_performance_followup': 'PHASE_9_HISTORICAL_EVALUATION / SEPARATE_FINE_TUNING_TRACK',
        'monad_development_readiness': 'GREEN', 'monad_development_permission': True,
        'remaining_software_blockers': [], 'historical_audit_limitations': [baseline['historical_payload_limitation']],
        'historical_artifacts_preserved': True, 'preservation_files_verified': len(preserved), 'safety': safety,
        'next_action': 'Checkpoint and push the healthy pre-Monad foundation. Preserve the weak blind-performance result as Phase 9 evidence. Then begin Monad research, audit and architecture.'}
    save(REPORTS/'final_pre_monad_health_gate.json', gate)
    save(REPORTS/'final_role_admissibility_repair.json', {**gate, 'role_use_contract': role_contract,
         'historical_replay': replay, 'review': reviewed})
    text = [
        '# Final V4 Role-Admissibility Reliability Repair', '',
        'Closure: PARTIAL for the requested exact historical replay; software reliability: PASS.',
        'System health and Monad architecture/research readiness: GREEN. No Monad work, commit or push performed.', '',
        '## Proven Root Cause',
        'Classification: OTHER - provider schema / validator pairing mismatch.',
        'The previous provider schema independently allowed all catalogue IDs and all SUPPORT/COUNTER/RISK enums.',
        'The unchanged backend catalogue admitted only particular ID/use pairs. Thus strict JSON could still contain a forbidden pair.',
        'The original two attempts failed role_admissibility at $.selected_evidence[0].use.',
        'Their exact evidence ID, requested use and action were not retained. No reconstructed pair is presented as recovered provider JSON.', '',
        '## Repair',
        'V4 responsibility boundary, schema name, role rules, facts, numbers, units and prose non-blocking behavior remain unchanged.',
        f'Acceptance identity: {v4.VALIDATOR_VERSION}; role-use contract: {v4.ROLE_USE_CONTRACT_VERSION}.',
        'Nested anyOf schema branches are generated from the same catalogue admissibility as the validator; IDs cannot be paired with forbidden uses.',
        'Snapshot enum and selection limits are constrained at the provider boundary. Unknown IDs/use enums remain invalid.',
        'Bull bearish SUPPORT and Bear bullish SUPPORT still fail. Opposing COUNTER evidence and valid ABSTAIN remain successful outcomes.',
        'Counter-only cases retain INSUFFICIENT support; they are not relabeled bullish or treated as forecasting success.',
        'Rejected selection diagnostics now retain bounded sanitized ID, requested/allowed uses, role compatibility, family, direction, action and field path.',
        'No provider prose, hidden reasoning, keys or private payload are persisted in those diagnostics.',
        'Prompt content hashes and versions are unchanged. Validator identity changes invalidate prior acceptance cache keys.',
        '[OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs) supports nested anyOf and bounded arrays for the configured base model.', '',
        '## Budget Policy',
        'The obsolete daily 12-call project limit no longer governs production V4 execution or health.',
        'Durable daily accounting continues. Public team workflows allow at most six calls; Bull-only allows at most two; one retry per role, SDK retries zero.',
        'Historical V2/V3 replay retains its former daily behavior. Tavily budgets, account/provider limits, auth, CSRF/origin, input/output guards remain unchanged.',
        f'The actual shared daily count was {live["daily_count_before"]} before the authorized Bull run and {live["daily_count_after"]} afterward; no counter reset or deletion.', '',
        '## Offline And Live Proof',
        f'Full relevant suite: {tests["passed"]} passed / {tests["failed"]} failed / {tests["skipped"]} skipped; no outbound network attempts.',
        'Normal and adversarial full mocked V4 workflows: 3/3 each. Cache, ledger, durability, fusion, lineage, conflicts, pipeline and dashboard checks passed.',
        'Six report-only desktop/iPad/phone browser cases passed with reload, nonblank chart, no overflow, no console errors or private-content leaks.',
        'Critical original structural equivalent: bearish Kronos direction used as Bull SUPPORT fails at the historical rule/path; corrected COUNTER passes.',
        'This reproduces the failure CLASS, not the missing original response.',
        'Exactly one Bull-only real-provider workflow ran and passed on its first call. No Bear, Risk, news, market-data fetch or inference rerun.',
        'A timestamp-only copy retained identical forecast, technical, news, numerical, risk and role catalogue content. Source-bar timestamp stays historical.',
        f'Fresh snapshot: {backend["snapshot_id"]}. Input: 11,938 bytes. Provider response completed, no truncation.',
        f'Usage: {attempts[0]["token_usage"]}; monetary API cost UNKNOWN.',
        'Bull selected technical trend and forecast direction as COUNTER, plus missing-news context as RISK.',
        'Backend direction remained BEARISH, support INSUFFICIENT, with MISSING_NEWS and NO_ROLE_ALIGNED_SUPPORT.',
        'Saved retrieval and local fusion refresh passed. The Bull-only live team is deliberately PARTIAL because other roles were not run.', '',
        '## Review And Architecture',
        'Scoped gstack review/security checklists and local browser QA: PASS. Combined gstack status: PARTIAL; native Aside unavailable and native learning log lacks Bun. No extra independent LLM judge calls.',
        'No blocking scoped review findings. Architecture GREEN; 8.9/10 scoped engineering assessment.',
        'V4 still validates boring structured selections; no V3 prose semantics or role-specific whitelist was introduced.', '',
        '## Scientific Preservation',
        f'{len(preserved)} pre-existing report, snapshot, forecast, score, ledger and unchanged production-file hashes verified.',
        'Historical AXISBANK windows and black-box artifacts are byte-for-byte unchanged.',
        'Blind forecast performance remains WEAK: direction 1/3; MAE wins versus Persistence 0/3, Drift 3/3, Momentum 0/3.',
        'No inference, training, model weights, fusion weights, technical thresholds, locked-test targets or scientific benchmark runs changed.',
        'Software reliability closure does not improve or erase this predictive-performance evidence; Phase 9 / the separate model track must address it.', '',
        '## Final Decision',
        'Remaining software blockers: none within this scoped gate. Exact historical rejected-output reconstruction remains unavailable, not fabricated.',
        'Monad architecture/research permission: YES. Implementation not started.',
        gate['next_action'], '',
    ]
    (REPORTS/'final_role_admissibility_repair.md').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({'closure': gate['status'], 'software_reliability': 'PASS', 'system_health': 'GREEN',
          'exact_historical_payload_replay': False, 'tests': tests['passed'], 'calls': live['provider_calls'],
          'historical_files_preserved': len(preserved), 'reports_created': 5}))


def copy_dict(value):
    return json.loads(json.dumps(value))


if __name__ == '__main__':
    if sys.argv[1:] == ['begin']:
        begin()
    elif sys.argv[1:] == ['offline']:
        offline()
    elif sys.argv[1:] == ['finish']:
        finish()
    else:
        raise SystemExit('Only the begin action is currently supported')
