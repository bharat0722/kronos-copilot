# Offline claim-contract compatibility repair

## Decision
**PASS offline. Bull/Bear/Risk GREEN offline. Live three-agent retest ready YES.**
Actual provider recovery remains unconfirmed. Monad permission remains NO and the existing failed-live gate/report are unchanged. No live test run here.

## Observed failures
Read both final live reports and all six sanitized first-failing claim diagnostics, not just their summary. Taxonomy counts: {"FACT_MISCLASSIFIED_AS_DIRECT": 4, "INTERPRETATION_MISLABELED_AS_FACT": 0, "MIXED_EVIDENCE_FAMILY": 2, "EVIDENCE_TYPE_MISMATCH": 0, "NUMERICAL_SUPPORT_MISMATCH": 0, "OTHER": 0}.
Bull/Bear described true bullish structured fields using extra factual labels. The strict direct-fact token rule rejected those words; this is not evidence of an invented bullish field. The safe repair steers cautious conclusions to explicit INTERPRETATION without broadening FACT acceptance. Risk cited FORECAST and RESEARCH_VIEW while declaring only one; use split observations, or the already-supported MULTI_SOURCE exception for an unavoidable cross-source conflict.

| Role | Attempt | Claim / support type | Declared family | Actual families | Rejection | Offline replay |
|---|---|---|---|---|---|---|
| bull | 1 | FACT / DIRECT | TECHNICAL | TECHNICAL | unsupported_direct_fact | reject preserved / correction PASS |
| bull | 2 | FACT / DIRECT | TECHNICAL | TECHNICAL | unsupported_direct_fact | reject preserved / correction PASS |
| bear | 1 | FACT / DIRECT | TECHNICAL | TECHNICAL | unsupported_direct_fact | reject preserved / correction PASS |
| bear | 2 | FACT / DIRECT | TECHNICAL | TECHNICAL | unsupported_direct_fact | reject preserved / correction PASS |
| risk | 1 | INTERPRETATION / INTERPRETIVE | RESEARCH_VIEW | FORECAST, RESEARCH_VIEW | incompatible_evidence_type | reject preserved / correction PASS |
| risk | 2 | INTERPRETATION / DERIVED | FORECAST | FORECAST, RESEARCH_VIEW | incompatible_evidence_type | reject preserved / correction PASS |

Exact rejected text, IDs, structured sources, and explicit corrected claims are in live_failure_replay_matrix.json. Corrections are offline-authored examples, not regenerated model outputs. All originals remain rejected. Do not reinterpret or overwrite prior accepted/rejected history.

## Implementation
Only production source changed: app/agent_research.py. Shared EVIDENCE_FAMILY_PREFIXES drives enum order, validation mapping and all role instructions. Diagnostic attempts now add actual_evidence_families, with original claim/type/support/IDs/reason retained. No private reasoning.
Bull prompt v7; Bear v6; Risk v6. The existing cache key includes prompt version and prompt hash; old-version success caches miss, and rejected outputs remain uncached. Existing agent_output_v2 schema and enums unchanged. Model gpt-5-mini, output1600, retry1, loop1, daily12, toolsNONE unchanged. Token-budget tuning was NOT reopened; the prior live truncation closure remains intact.

## Contract
FACT/DIRECT is a short exact qualitative source observation, not a synthesized momentum/demand/causality conclusion. NUMERICAL_FACT/DIRECT keeps exact field/value/unit matching, preferably field + value. Interpretations use DERIVED/INTERPRETIVE and cautious framing, real IDs, compatible families; numbers inside interpretations still undergo exact numerical checks. Split observations by family; same-family multiple IDs remain a single type. Existing MULTI_SOURCE handles a genuine cross-family argument/conflict without new schema fields. COMPARATIVE needs both families and DERIVED/MIXED support.
Risk/limitation/uncertainty instructions cite actual risk, absence, conflict or calibration states. No free-form summary/new financial facts. Shared generation guidance is narrower, while the existing validation functions are untouched; no universal NLP entailment or broad new validator is introduced. FORECAST_INTERPRETATION still requires FORECAST evidence. See evidence_family_contract.json for all actual catalog namespaces and category rules.

## Tests and audit
**217 passed /0failed /1skipped**,218 total. The skip is the existing opt-in live Yahoo test. External calls0 and blocked external attempts0. New16tests replay all six failures, supported/unsupported facts, fact/interpretation typing, family mismatch, invalid IDs, same-family multiple IDs, split Risk observations, cross-source conflicts, missing evidence, numeric value/unit failures, old prompt cache invalidation, ledger diagnostics and full mocked integration.
Production-sized synthetic team:3/3 accepted, COMPLETE,3mock requests, input41477 bytes. Actual unchanged Team.run -> strict parser/validators -> durable ledger -> cache; restart retrieval retains COMPLETE. Deterministic fusion invalidates pre-agent cache, includes valid derived agents without mutating input. A separate persisted mock artifact is under claim_contract_mock_team; its local mock budget is not the real production usage database.
Browser QA PASS at1440,390,834: auth-dialog interaction with synthetic code, failed/reload, complete, partial, stale-disabled, one mocked run on double-click, no overflow/errors/external requests, nonblank chart. APIs intercepted, never paid. Existing true backend auth/static/cross-site/cost regressions ran in the offline suite. Screenshots in claim_contract_qa.
Architecture PASS: one shared contract/helper, no duplicated validator, no role-specific validation hack, schema unchanged, no source/fusion/server/dashboard changes this task. Ten validator/schema/freshness/concise/budget function AST hashes match the pre-task baseline. Original live evidence and Phase8 reports match baseline hashes (27 preserved artifacts). Source integrity confirms only the agent contract source changed from the already dirty repair state. git diff --check passed.

## Gstack coverage
PARTIAL tooling coverage; repository version 1.91.2.0. Applied the read review/checklist.md critical and informational passes plus sequential skeptical trust-boundary review. No supported blocking finding in the modified contract. Report-only local Playwright QA completed. Native CSO NOT ASSESSED: trusted installed launcher absent; no repository execution bypass. Shared startup, remote diff fetch, telemetry/sync and outside-model review not run: offline constraints and missing Bash. No dependency installation or paid call. This is not a claim that native gstack CSO or an independent external reviewer passed.
RESOLVED: factual-wording compatibility and mixed-family guidance in deterministic replays. NON-BLOCKER: unavailable native CSO/outside-model tooling; existing synthetic QA helper NumPy timedelta deprecation warning. BLOCKER: none offline. Live generation remains the next separate verification requirement.

## Safety and Git
Branch monad-metropolis, dirty on entry and still dirty. Existing unrelated changes preserved. No commit or push. OpenAI/Yahoo/Tavily/Monad/other LLM0. Kronos inference/training/weights0. Validation rerunNO, locked test untouched, Monad implementation not started. Synthetic technical/forecast values and mock requests are not model inference or historical evaluation.
Files changed this task: app/agent_research.py, research/tests/test_phase7_2e_numeric_grounding.py, research/tests/test_phase7_2f1_bull_only.py, research/tests/test_phase7_3b_agent_output_v2.py, research/tests/test_claim_contract_repair.py, research/tests/fixtures/claim_contract_live_rejections.json, tools/run_offline_health_tests.py. Generated reports: claim_contract_repair.md/.json, evidence_family_contract.json, live_failure_replay_matrix.json, test/QA artifacts and isolated mock ledger/cache. Preexisting live reports/readiness gate were not rewritten.

## Limitations and next action
Mock/replay success cannot prove the provider will obey new prompts. Only sanitized first-failing claims are available, not every claim from complete rejected live responses. The Phase7 semantic contract is bounded, not a universal entailment verifier. No statistical confidence/forecast-accuracy improvement claim.
**Obtain fresh authorization for exactly one final production-like synthetic three-agent OpenAI retest.**
Do not execute that retest or start Monad here. STOP.
