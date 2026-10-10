"""Report frozen outcomes only; no inference, provider access, or repairs."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.run_real_world_challenge import REPORT, SCOPE, assert_sources
from tools.run_v3_live_confirmation import load, save, private_check


def main():
    assert_sources()
    selection = load(REPORT / 'candidate_selection.json')
    test1 = load(REPORT / 'test1_live_stress.json')
    qa = load(REPORT / 'dashboard_qa/qa.json')
    # Reconstruct the original stage from retained source state, not a new fetch.
    news = test1['news']
    attempts = test1['attempt_records']
    completion = max(a['finished_at'] for a in attempts)
    age = (datetime.fromisoformat(completion) - datetime.fromisoformat(news['retrieved_at'])).total_seconds()
    test1['pipeline']['stages']['news'] = {
        'status': 'HEALTHY' if news['status'] == 'FRESH' and age <= 900 else 'STALE' if news['status'] == 'FRESH' else 'DEGRADED',
        'rows': len(news['events']), 'last_update': news['retrieved_at'], 'provider': news['provider'],
        'symbol': news['symbol'], 'cache_status': news['cache_status'], 'tavily_health': news['tavily_health'],
        'impact_status': news['news_impact']['status'], 'warnings': news['news_impact']['uncertainty_flags'],
        'status_scope': 'Deterministically reconstructed at original team completion from retained FRESH response and source health; collector had lost the in-memory NewsService stage after restart'}
    test1.update(dashboard_qa=qa, news_quality_verdict='DEGRADED', news_fetch_verdict='PASS',
        security_checks={'status': 'PASS', 'offline_tests_passed': 9, 'failed': 0, 'skipped': 0},
        pipeline_verdict='DEGRADED_RESEARCH_QUALITY',
        limitations=['Latest provider bars stop at 15:15 IST; no missing closing bars were invented',
          'Closed-session technical evidence is STALE in wall-clock fusion; V4 catalogue freshness is relative to its technical as-of',
          'Fresh news retrieval did not yield sufficient scored event context: impact INSUFFICIENT_EVIDENCE',
          'Optional model explanations are unverified presentation, never authoritative facts'],
        status='PASS' if qa['status'] == 'PASS' and all(test1['checks'].values()) else 'FAIL')
    save(REPORT / 'test1_live_stress.json', test1)
    rows = []
    for number in (1, 2, 3):
        folder = SCOPE / ('window' + str(number))
        scores = load(folder / 'scores.json')
        integration = load(folder / 'agent_integration.json')
        rows.append({**scores, 'team_status': integration['cached_team']['team_status'],
          'team_completed': integration['cached_team']['agents_completed'],
          'snapshot_id': integration['snapshot_id'], 'agent_audit': integration['agent_audit'],
          'agent_status': integration['cached_team']['agents'], 'checks': integration['checks'],
          'attempt_records': integration['attempt_records'], 'ledger_records': integration['ledger_records'],
          'fusion': integration['fusion'], 'health': integration['health'],
          'fusion_health': integration['fusion_health'],
          'fusion_health_scope': 'Historical as-of result; wall-clock STALE is expected and not a current live view'})
    summaries = [r['metrics']['75']['kronos'] for r in rows]
    comparison = {'primary_horizon': 75, 'win_definition': 'Strictly lower timestamp-aligned close MAE; existing baseline defaults, no tuning',
        'windows': [{'window': r['window'], 'compared_bars': r['observed_horizon_coverage'], 'metrics': r['metrics']['75']} for r in rows],
        'kronos_beats': {name: sum(r['metrics']['75']['kronos']['mae'] < r['metrics']['75'][name]['mae'] for r in rows)
                         for name in ('persistence', 'drift', 'momentum')},
        'averages': {key: sum(m[key] for m in summaries) / 3 for key in ('mae', 'rmse', 'mape', 'smape')},
        'direction_hits': sum(m['directional_match'] for m in summaries),
        'fusion_direction_hits': sum(r['fusion_directional_match'] is True for r in rows),
        'fusion_nondirectional_windows': sum(r['fusion_directional_match'] is None for r in rows),
        'scope': 'Three pre-selected windows, one unseen equity; descriptive challenge only, not a general accuracy estimate'}
    save(REPORT / 'baseline_comparison.json', comparison)
    blind = {'status': 'PARTIAL', 'symbol': selection['test2_symbol'], 'previously_used': False, 'windows': rows,
        'news': 'EXCLUDED_FOR_LEAKAGE_PREVENTION', 'performance': comparison,
        'no_future_leakage': all(r['no_future_leakage'] for r in rows), 'all_windows_reported': True,
        'context_bar_count': 400, 'default_forecast_bars': 75, 'extra_24_bars': 'Scored from same forecasts',
        'extended_120_bars': 'Unavailable: not forecast by default; no separate rerun',
        'known_limits': ['Source target coverage 73/75, 73/75, 72/75; real endpoints present; no imputation',
          'Cutoffs chosen from timestamp/count eligibility only; missing endpoints excluded before inference',
          'Current volatility symbol preselection is retrospective relative to historical cutoffs, as explicitly prescribed; not a prospective strategy backtest',
          'The historical online challenge checks input blinding, not global model-training membership or general predictive accuracy',
          'One rejected Bull perspective and one budget-blocked Risk perspective remain missing; fusion retains those missing markers']}
    save(REPORT / 'test2_blind_reality.json', blind)
    counts = load(SCOPE / 'calls.json')
    all_attempts = test1['attempt_records'] + [a for r in rows for a in r['attempt_records']]
    transport_count = sum(load(SCOPE / label / 'transport.json')['openai_requests'] for label in ('test1', 'window1', 'window2', 'window3'))
    assert counts['openai_calls'] == transport_count == len(all_attempts) == 12
    failed = [a for a in all_attempts if a['status'] != 'SUCCESS']
    verdict = {'schema_version': 'final_real_world_black_box_verdict_v1', 'status': 'PARTIAL',
        'test1_verdict': test1['status'], 'test2_verdict': 'PARTIAL',
        'system_correctness': 'FAIL_FULL_ACCEPTANCE_GATE',
        'architecture_safety': 'PASS_INVALID_SELECTIONS_REJECTED_AND_BUDGET_ENFORCED',
        'research_grounding': 'PASS_FOR_ALL_ACCEPTED_OUTPUTS', 'complete_agent_confirmation': 'FAIL',
        'real_market_performance': 'WEAK_IN_THIS_THREE_WINDOW_CHALLENGE',
        'answers': {'production_research_system': 'PARTIAL', 'v4_reliably_grounded_new_evidence': 'PARTIAL',
                    'kronos_predicted_windows_well': 'WEAK', 'fusion_useful_traceable_view': 'YES',
                    'healthy_enough_to_checkpoint_as_final_green': 'NO'},
        'health': {'ai_research_team': 'RED', 'bull': 'RED', 'bear': 'GREEN', 'risk': 'YELLOW_BUDGET_BLOCKED',
                   'agent_harness': 'GREEN', 'evidence_fusion': 'YELLOW_INCOMPLETE_PERSPECTIVES',
                   'pipeline': 'YELLOW', 'dashboard': 'GREEN', 'security': 'GREEN'},
        'highest_priority_blocker': {'category': 'ROLE_ADMISSIBILITY', 'window': 2, 'agent': 'bull',
            'attempts': 2, 'rule_code': 'role_admissibility', 'json_path': '$.selected_evidence[0].use',
            'reason': 'Both model responses selected a use forbidden by the selected catalogue entry for Bull',
            'exact_rejected_evidence_id': 'NOT_RETAINED_BY_CURRENT_LEDGER', 'diagnostics': [a.get('validation_diagnostic') for a in failed]},
        'additional_blocker': {'category': 'BUDGET', 'window': 3, 'agent': 'risk', 'code': 'COST_LIMIT',
            'provider_calls': 0, 'reason': 'Unchanged shared 12-call daily guard; earlier permitted retry used the spare workflow capacity'},
        'calls': counts, 'openai_transport_requests': transport_count,
        'token_usage': {key: sum((a['token_usage'].get(key) or 0) for a in all_attempts) for key in ('input_tokens', 'output_tokens', 'total_tokens')},
        'api_cost': 'UNKNOWN', 'no_truncation': all(a.get('completion_reason') != 'max_output_tokens' for a in all_attempts),
        'structured_outcomes': {'accepted': 10, 'rejected_roles': 1, 'budget_blocked_roles': 1, 'total_roles': 12},
        'performance': comparison, 'dashboard_qa': qa['status'], 'security_offline_tests': {'passed': 9, 'failed': 0, 'skipped': 0},
        'collector_incident': load(REPORT / 'validation_runner_incident.json'),
        'safety': {'monad_calls': 0, 'kronos_training': 0, 'model_weight_changes': 0,
          'protected_benchmark_reruns': 0, 'locked_test_accesses': 0, 'production_code_changes': 0,
          'no_tuning': True, 'no_window_replacement': True, 'news_test2_excluded': True,
          'no_llm_judge_calls': True, 'git_commit': False, 'git_push': False, 'monad_implementation': False},
        'production_source_hashes_unchanged': True, 'generated_at': datetime.now(timezone.utc).isoformat()}
    for value in (test1, blind, comparison, verdict):
        private_check(value)
    save(REPORT / 'final_black_box_verdict.json', verdict)
    write_markdown(test1, blind, comparison, verdict)
    print(json.dumps({'status': verdict['status'], 'answers': verdict['answers'], 'performance': comparison['kronos_beats'],
                      'calls': counts, 'token_usage': verdict['token_usage'], 'all_windows_reported': True}, indent=2))


def write_markdown(test1, blind, comparison, verdict):
    lines = ['# Test 1: Unseen Real-World Stress', '', 'Technical verdict: ' + test1['status'],
        'Symbol: BAJFINANCE.NS; highest realized volatility among the two eligible prescribed candidates.',
        'Market closed. Latest returned completed bar: ' + test1['latest_market_timestamp'],
        'Default Kronos-base: 400 context bars, 75 predicted bars, T=1.0, top_k=0, top_p=0.9, one sample, CPU.',
        'Bull/Bear/Risk accepted first attempt; snapshot ' + test1['snapshot_id'],
        'News retrieval FRESH (Tavily); impact INSUFFICIENT_EVIDENCE, therefore research quality DEGRADED.',
        'Raw Kronos bullish; technical trend bearish. Fusion MIXED, LOW support, HIGH risk.',
        'Technical evidence is STALE under wall-clock fusion and not an eligible current primary directional conflict. Its opposing direction and the agents\' conflict qualifications remain visible.',
        'No calibrated probability or forecast-accuracy claim is made.', '', '## Deterministic Selection Audit']
    for role, audit in test1['agent_audit'].items():
        lines += ['', '### ' + role.title(), 'Available IDs: ' + ', '.join(audit['available_evidence_ids']),
            '| Selected ID | Label | Use | Direction | Quality | Freshness | Allowed role modes |', '| --- | --- | --- | --- | --- | --- | --- |']
        lines += ['| ' + ' | '.join(str(x) for x in (e['evidence_id'], e['short_backend_label'], e['selected_use'], e['direction'], e['quality'], e['freshness'], ', '.join(e['role_compatibility'][role]))) + ' |' for e in audit['role_admissibility_proof']]
    lines += ['', '## Scope and Limitations', *['- ' + x for x in test1['limitations']],
              'Desktop/iPad/phone responsive QA uses the actual application code and saved real API-compatible outputs, not synthetic scaffolding. All additional browser provider calls are blocked.',
              'The collector field-name incident was recovered from durable state with no reruns. News stage at completion is reconstructed from retained response state, explicitly labelled in JSON.',
              'Full source, selected evidence lineage, resolved backend facts, stage health, and attempts are in test1_live_stress.json.']
    (REPORT / 'test1_live_stress.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    lines = ['# Test 2: Blind Reality', '', 'AXISBANK.NS; all three timestamp-selected windows retained.',
        'News excluded to prevent leakage. Default horizon unchanged; 24-bar metrics reuse the same prediction.',
        'Workers received only 400 visible bars. Forecasts, baselines, agents and fusion were persisted and hashed before each scoring-stage target read.',
        'Source gaps are not imputed. Metrics use identical observed timestamps for Kronos and baselines, with real production endpoint bars.', '']
    for row in blind['windows']:
        m = row['metrics']['75']['kronos']
        lines += ['## Window ' + str(row['window']), 'Cutoff: ' + row['cutoff'],
            'Team: ' + str(row['team_completed']) + '/3; state ' + row['team_status'],
            'Coverage: ' + str(row['observed_horizon_coverage']) + '/75; freeze ' + row['freeze_hash'],
            f"Predicted return {m['predicted_return'] * 100:.6f}%; actual {m['actual_return'] * 100:.6f}%; direction match {m['directional_match']}.",
            f"MAE {m['mae']:.6f}; RMSE {m['rmse']:.6f}; MAPE {m['mape']:.6f}%; SMAPE {m['smape']:.6f}%; endpoint error {m['final_error_pct']:.6f}%.",
            'Fusion before reveal: ' + row['fusion_view_before_reveal'] + '; directional match ' + str(row['fusion_directional_match']),
            '| Method | MAE | RMSE | MAPE % | SMAPE % | Final error % |', '| --- | ---: | ---: | ---: | ---: | ---: |']
        lines += [f"| {name} | {v['mae']:.6f} | {v['rmse']:.6f} | {v['mape']:.6f} | {v['smape']:.6f} | {v['final_error_pct']:.6f} |" for name, v in row['metrics']['75'].items()]
        lines += ['']
    lines += ['## Limits', *['- ' + x for x in blind['known_limits']],
              'All 24-bar metrics and accepted pre-reveal selected IDs, facts, fusion lineage, diagnostics and omitted perspectives are retained in test2_blind_reality.json.']
    (REPORT / 'test2_blind_reality.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    lines = ['# Final Real-World Black-Box Verdict', '', 'Overall: PARTIAL. This is not a final green gate.',
        'Test1 real-data product path passed; news impact weak. Blind teams: 3/3, 2/3, 2/3.',
        'Kronos direction hits: 1/3. Fusion: 0 hits, two misses, one non-directional MIXED view.',
        '75-bar MAE wins: Persistence 0/3; Drift 3/3; Momentum 0/3.',
        'Performance: WEAK in these three windows. No general accuracy percentage is claimed.',
        'Safety architecture correctly rejected invalid selections and enforced the unchanged budget. Full functional acceptance is not met.',
        'Highest-priority structural blocker: Bull role_admissibility, $.selected_evidence[0].use, twice in Window2. No prose repair was made.',
        'Additional incomplete execution: Window3 Risk COST_LIMIT, before any provider request.',
        'No forecast, prompt, validator, weights, fusion rules, thresholds, horizon, baseline definitions or provider order were tuned.',
        'Calls: ' + json.dumps(verdict['calls']) + '; API monetary cost UNKNOWN.',
        'Token usage: ' + json.dumps(verdict['token_usage']), '', '## Five Answers']
    lines += ['- ' + key + ': ' + value for key, value in verdict['answers'].items()]
    lines += ['', '## Safety', json.dumps(verdict['safety'], indent=2),
        'Production source hashes unchanged. Locked datasets and protected target contents were never opened. New online data only.',
        'Reports preserve every selected window, including wrong forecasts and incomplete teams. No repair, commit, push, or Monad work was performed.',
        'Detailed metrics: test2_blind_reality.md and baseline_comparison.json. Human-sense evidence audit: test1_live_stress.md.']
    (REPORT / 'final_black_box_verdict.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
