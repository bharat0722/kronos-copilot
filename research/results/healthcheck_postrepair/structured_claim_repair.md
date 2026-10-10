# Structured Claim and Numerical Grounding Robustness Repair

## Decision

**Offline repair: PASS.** Bull, Bear and Risk are GREEN OFFLINE. The AI Research Team remains YELLOW PENDING LIVE; Monad development permission remains NO. No live call was made.

Current contract: `agent_output_v2_1`, Bull `bull_agent_prompt_v8`, Bear `bear_agent_prompt_v7`, Risk `risk_agent_prompt_v7`. Shared fact validator: `structured_claim_grounding_v1`; numerical validator: `numerical_grounding_v4`.

## Observed Root Cause

The latest Test A produced six completed provider responses and no accepted agent output. Four Bull/Bear rejections came from using free-form prose for FACT/DIRECT support; two Risk rejections came from field/unit recognition in numerical prose. The Risk values 101.2 and 1.2 exist in the cited evidence. The problem was not evidence that those numbers were fabricated: underscore field names were not recognized by the old word-boundary matcher, and the percentage lacked its explicit unit.

The retained Risk numerical diagnostics do not include original claim/support taxonomy. This audit does not invent those missing fields or reconstruct an entire provider output. Both numerical-fact and derived-risk structural equivalents are tested. Exact text, references and original diagnostic reasons are retained in `live_shape_replay_v2.json`.

| Primary failure category | Count |
| --- | ---: |
| DIRECT_FACT_PARAPHRASE | 3 |
| FACT_AND_INTERPRETATION_COMBINED | 1 |
| FIELD_ALIAS_MISMATCH | 2 |

Risk attempt 1 additionally demonstrates an explicit percentage-unit/wording mismatch. These counts classify diagnostics conservatively, not a new model-quality metric.

## Contract Repair

`app/structured_claims.py` provides one shared deterministic field resolver and fact validator used by all three agents. Facts require `field_key`, `value`, `unit`, cited evidence and DIRECT single-family support. Their `text` is empty; presentation text is derived from the validated tuple. FACT is an exact source state/string; NUMERICAL_FACT is an exact finite JSON number bound to its specific cited field. Booleans, numeric strings, NaN, infinity, wrong values, fields, units and signs fail.

Aliases are explicit, limited and deterministic. No fuzzy field matching, sentence whitelist, arbitrary unit conversion or automatic factual rewriting is used. Implemented production labels such as ATR14, ROC10, MACD signal and Volume SMA20 have exact mappings alongside the existing synthetic fixture labels. Native price units do not infer INR/USD. Explicit currency requires cited currency metadata. A negative forecast return and its positive downside magnitude are equivalent; an upside assertion with a negative value fails.

Interpretations retain cautious text, typed support and compatible references. Their structured fact fields must all be null. Existing prose numerical guards remain active, with explicit signed-direction checks and bounded known-state contradiction checks. This is not universal semantic entailment. Numbers appearing only in a headline cannot be promoted through a string FACT into a numerical fact.

The required nullable scalar fields remain in a closed strict schema. Field enums are limited to snapshot-citable fields; the backend still validates the exact field/value/unit binding. The local strict preflight accepts only supported nullable scalar combinations. No API family, model, tools, loop, retry, daily cap or input/output budget was changed.

## Ownership, Cache and Ledger

Existing AgentTeam orchestration owns validation, durable attempts/runs, cache and published team state. Successful validation still precedes durable ledger commit, then cache/publish. Failed claims remain unusable and uncached. Cache identity includes snapshot, role, model, prompt version/hash, output schema, configuration, numerical and structured validator versions. Old v2 outputs are not silently accepted as v2_1.

Claim metadata hashes include the complete typed claim, including structured field/value/unit/direction and lineage. Sanitized diagnostics retain bounded field details without credentials, filesystem paths, malformed objects or non-finite JSON values. Historical reports and frozen fixtures were verified byte-identical to the baseline.

## Offline Validation

**253 passed / 0 failed / 1 skipped**, 254 tests run. The skipped test is the existing explicitly opt-in live Yahoo regression. External connection and DNS attempts were blocked by the runner; blocked external attempts = 0. No training, inference, validation evaluation or locked-test access occurred.

Coverage includes exact live-shape rejection and corrected-shape acceptance, supported facts, wrong RSI/price/return/unit/sign, unsupported fields/volume/states, missing/wrong references/families, mixed-family policy, interpretations, headline-number bypass, real indicator labels, strict schema preflight, cache version changes, durable ledger/status, failure handling, fusion, immutability, serialization boundaries and LAN/cross-site/security controls.

| Fixture | Exact bytes | Mocked team | Fusion/cache/lineage/durability |
| --- | ---: | --- | --- |
| synthetic_production_v1_TESTCO | 21,420 | 3/3 | PASS |
| synthetic_adversarial_v1_TESTCO | 21,834 | 3/3 | PASS |

Original frozen JSON and hashes remain unchanged. Historical frozen fixtures were replayed at their recorded timestamp through the unchanged freshness guard, not refreshed or made live-eligible. Both cases preserve all six evidence families, twelve indicators, eight articles/events and adversarial conflicts. Corrected claims do not alter upstream evidence.

## Dashboard and Scoped Gstack Review

Installed gstack `review`, `cso` and `qa-only` documentation/checklists were read and applied to the scoped repair. Native runtime availability is incomplete: the installed browse distribution is absent, no Bash command is on PATH and no installed package/version metadata was found. No upgrade, telemetry, outside-model review or external dependency check was run. **Gstack workflow status: PARTIAL; local scoped code/security checklist review and intercepted browser QA: PASS.** This is not a claim that a full native gstack security audit ran.

Desktop 1440px, phone 390px and iPad 834px browser checks passed initial render and reload. All requests were intercepted locally. Structured facts render via textContent, all three agent cards are Complete, and computed mocked pipeline health reports 3/3. No overflow, console/page errors, blocked unexpected requests, secrets or paths were observed. The existing synthetic chart loaded; this focused replay does not prove live market/news/chart data alignment or live LAN reachability.

Three scoped issues were closed during review: exact production indicator-label bindings, a Risk card that ignored model/event/data/conflict categories and incorrectly showed unknown, and unstructured headline numbers bypassing fact typing. Their regression tests pass. The Risk-card change only extends the existing compact display; it does not redesign the dashboard or change forecast values.

## Architecture Recheck

**Custom scoped architecture score: 8.6/10.** This is not a gstack composite health score. One shared binding module, shared role validation, explicit schema/prompt versions, unchanged cache/ledger ownership and a small rendering adapter improve the evidence boundary. No server.py edits, new dependency, provider, agent, tool, forecast calculation or fusion weighting change was introduced.

Accepted limitations: qualitative interpretation is not independently semantically verified; the real provider has not yet confirmed the new contract; server.py remains the pre-existing broad orchestrator. No actionable offline blocker remains in this repair. Offline success does not make the live team GREEN or establish forecasting accuracy.

## Final Manifest and Execution Conditions

`final_dual_live_retest_manifest.json` freezes original fixture identities, schema/validator/prompt versions and hashes, final source hashes, model and budgets. Input maximum remains 48,000 bytes; output maximum remains 1,600 tokens; loop = 1; retry = 1; tools = NONE; daily call cap = 12; two future workflows have an absolute maximum of 12 provider calls.

**Ready for immediate live execution: NO.** The production budget was read-only verified at 12/12 for 2026-10-09 UTC. The original snapshots, frozen at 13:54:18 UTC, expired at 14:54:18 UTC. The manifest explicitly blocks silent timestamp refresh or cap reset. A later run needs fresh authorization, sufficient naturally renewed budget and a separately authorized timestamp-only deterministic re-freeze before any provider request. Existing manifest hashes must not be silently reinterpreted as new snapshots.

No commit or push was made; branch remains `monad-metropolis`, with pre-existing dirty work preserved. Earlier failed live reports and the readiness gate were not overwritten as successful live evidence.

## Next Action

Obtain authorization for a fresh timestamp-only fixture freeze and the final normal/adversarial live Agent Team retests after the daily budget resets. Do not execute them as part of this task.
