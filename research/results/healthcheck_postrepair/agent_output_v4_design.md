# Agent Output V4: Evidence Selection and Backend Truth

## Verdict

- V4 implementation and offline validation: **PASS**.
- The prose-wording-to-structured-rejection loop is **ELIMINATED BY DESIGN** for V4. This is not a guarantee that providers always return valid JSON, IDs, actions or ranks.
- Normal and adversarial mocked production workflows: **3/3 valid each**.
- Relevant offline suite: **392 passed, 0 failed, 1 skipped**; 393 tests run. The skip remains the explicitly opt-in live Yahoo regression. Network calls and blocked external attempts: zero.
- Bull, Bear, Risk and harness: **GREEN OFFLINE**. AI Research Team: **YELLOW PENDING V4 LIVE CONFIRMATION**. Monad development permission: **NO**.
- Scoped architecture assessment: **8.8/10**. gstack: **PARTIAL overall**; scoped review/security checklists and native browser QA passed. No external-model or remote PR review was performed.

## Responsibility Boundary

```text
Immutable EvidenceSnapshot
  -> backend admissible catalogue
  -> model selects IDs, use modes and ranks
  -> deterministic structural validation
  -> backend resolves facts, direction, conflicts and limitations
  -> derived-evidence fusion adapter
  -> existing dashboard and pipeline health

Optional model explanation -> safety filter -> unverified display OR backend fallback
                            (never a structured acceptance or fusion input)
```

The backend exclusively owns field identity, values, numbers, units, canonical direction, evidence family, freshness/quality, source lineage, selected-evidence conflicts and support/uncertainty state. The model selects and prioritizes admissible evidence from a bounded catalogue. It may supply a non-authoritative explanation; it cannot supply a new factual field or stance.

Versions:

| Component | Version |
| --- | --- |
| Output | `agent_output_v4` |
| Acceptance validator | `evidence_selection_validator_v1` |
| Catalogue | `admissible_evidence_catalogue_v1` |
| Backend renderer | `evidence_selection_renderer_v1` |
| Bull prompt | `bull_agent_prompt_v10` |
| Bear prompt | `bear_agent_prompt_v9` |
| Risk prompt | `risk_agent_prompt_v9` |

Historical V2, V2.1 and V3 contracts remain isolated. V4 reuses only the existing canonical fact catalogue/renderer from V3, not its semantic prose acceptance validator. Legacy tests explicitly select their historical harness/prompt/schema versions rather than silently exercising the new production default. Historical results are not reinterpreted or converted into accepted V4 outputs.

## Minimal Wire Contract

The model returns six top-level fields: `schema_version`, `agent_type`, `snapshot_id`, `action`, `selected_evidence`, and nullable `optional_explanation`. Each selection contains only `evidence_id`, `priority` and `use`. Strict JSON Schema disables additional properties and enumerates available IDs, roles, actions, modes and allowed priorities.

Structural acceptance checks identity, action, count, exact selection shape, known IDs, duplicate IDs, consecutive ranks and backend role/mode compatibility. It does not judge whether the model chose the best possible ranking. Unknown IDs, fabricated fields, wrong snapshots, wrong roles, forbidden modes and malformed JSON remain genuine failures. Optional explanation content is not an acceptance predicate.

| Role | Limit | Actions | Selection modes |
| --- | --- | --- | --- |
| Bull | 3 | PRESENT_CASE, ABSTAIN | SUPPORT for eligible bullish evidence; COUNTER for bearish evidence; RISK for qualifications |
| Bear | 3 | PRESENT_CASE, ABSTAIN | Symmetric opposite-direction policy |
| Risk | 4 | FLAG_RISK, ABSTAIN | RISK only, for directional fragility, quality/freshness limits, conflicts and missing evidence |

Neutral/non-directional evidence can qualify a case where the catalogue allows it; it cannot be silently promoted into directional support. Duplicate selections are rejected. ABSTAIN requires an empty selection array and is a valid completed outcome. A valid counter-only case remains accepted but has `INSUFFICIENT` role-aligned support and `NO_ROLE_ALIGNED_SUPPORT`; it is not invented bullish/bearish conviction.

## Catalogue and Backend Result

The compact catalogue includes canonical IDs, family, backend direction, risk relevance/flags, role-compatible modes, quality, freshness, available fact field keys, backend label, timestamp and provenance/lineage references. It does not transmit full provider article bodies, arbitrary raw text or private metadata. Canonical facts are resolved locally after selection.

Quality FAIL and freshness STALE cannot support or oppose a directional case; they can be selected as explicit limitations. Existing snapshot freshness preflight remains active. Per-item freshness is measured relative to the snapshot's existing technical/market timestamp: market evidence up to one hour is fresh and up to one day aging; news up to three days is fresh and up to seven days aging. Missing/future/unparseable timestamps are UNKNOWN, not fabricated current timestamps. These are transparent v1 rules, not calibrated trading thresholds.

Backend context items identify directional disagreement and missing usable primary families. News impact alone is not treated as present news when no article/event evidence exists. Conflict context preserves its underlying evidence lineage. Pipeline/market quality remains meta-evidence, not bearish price direction.

Selected backend directions determine BULLISH, BEARISH, MIXED, NEUTRAL or UNCERTAIN. Support is INSUFFICIENT, LOW or MEDIUM under conservative rules; no probability or statistically calibrated confidence is created. Risk affects limitations/support rather than automatically reversing price direction. The resulting object contains resolved facts, selected items, action, direction, conflict, support, uncertainty flags, risk, explanation status and lineage.

## Non-Blocking Explanation

Safe optional prose is labelled `VALID_UNVERIFIED` and displayed as an optional, unverified perspective. Empty/null prose is OMITTED. Numeric, unsafe, excessively long, malformed or sensitive prose is REJECTED and discarded. A deterministic fallback is rendered from backend catalogue labels and structured conflict state. REJECTED/OMITTED explanation statuses never convert valid selections into an agent failure or a retry.

The safety filter is deliberately not universal semantic entailment. An unsupported qualitative sentence could pass lightweight safety checks, so accepted prose is explicitly non-authoritative and never contributes facts, direction, claims or weights to Evidence Fusion. Backend-rendered canonical facts remain separate in the dashboard. No hidden reasoning is requested or persisted.

Critical regression proofs in `research/tests/test_agent_output_v4.py` include `test_number_explanation_nonblocking`, `test_arbitrary_wording_nonblocking`, `test_garbage_explanation_nonblocking`, `test_bad_explanation_team_complete`, `test_prose_never_enters_fusion`, `test_backend_direction_not_prose`, and `test_unsafe_prose_not_stored_in_ledger`.

## Harness, Cache, Ledger and Team State

The supported production AgentTeam path defaults to V4 and explicitly dispatches V4 input/schema/validation/presentation. Historical helper interfaces remain available to the frozen legacy harnesses. Model `gpt-5-mini`, max input 48,000 bytes, max output 1,600 tokens, loop one, retry one, tools NONE and existing budget safeguards are unchanged. The OpenAI SDK path is unchanged; no live invocation occurred.

Cache identity includes snapshot, role, model, prompt, schema, validator and configuration/prompt identity. V3 caches cannot satisfy V4. Durable team files and latest-state pointers are contract-specific. Structured acceptance, selected IDs, action and explanation status are separately observable in attempts/run rows. Successful validated results still require durable ledger commit before cache/publish. Ledger or cache failures do not create a falsely usable successful result.

All three valid structured outcomes, including abstentions or explanation fallbacks, produce COMPLETE. Provider/schema/structural/persistence failures still produce truthful partial/failed state. The normal retrieval path reloads snapshot-owned durable results without provider calls.

## Fusion and Dashboard

The adapter represents an agent's prioritization of upstream canonical evidence as DERIVED evidence. It carries shared primary lineage, backend direction/risk/support, and no optional prose. Agent prioritization adds no independent primary directional vote; existing fusion rules/weights are unchanged. Shared selections across roles do not duplicate the original forecast/news/technical influence. A valid abstention is present as an agent outcome with zero support, not a fabricated neutral primary signal.

Existing Bull/Bear/Risk cards show backend labels, selection use, canonical facts and separately identified explanation/fallback. No raw giant response is displayed. Pipeline health reports a complete structured team as HEALTHY even if explanations are rejected. The adversarial case retains disagreement, elevated volatility and insufficient role-aligned support rather than silently resolving them.

See `v4_fusion_adapter_report.md`, `v4_mocked_workflows.json`, and the browser QA reports for integration evidence.

## Historical Failure Elimination

The inventory reconciles **48 unique retained rejected attempts** across earlier live artifacts. Eleven observed categories are classified: nine semantic/model-authored-content failure classes are removed from V4 structured acceptance; two structural classes intentionally remain relevant.

Removed/non-blocking classes include direct-fact paraphrases, field/value/unit authoring, evidence-family declarations, numerical prose, string/prose constraints, hedge keywords and model-authored directional conflict. Unknown/duplicate/missing evidence selection and malformed/schema/provider/system failure remain enforceable. Role admissibility remains necessary even though semantic family declaration is no longer model-owned.

Each retained failure is evaluated using a valid V4 structural equivalent. Retained prose is replayed where available; where exact prior text was not retained, the artifact explicitly records structural-equivalent-only evidence. No missing verbatim text is invented. This proves the responsibility-boundary change, not that historically rejected V2/V3 outputs have become accepted retroactively. Details: `v4_failure_elimination_matrix.json`.

## Measured Complexity

| Measure | V3 | V4 |
| --- | ---: | ---: |
| Schema property occurrences | 24 | 9 |
| Primary validator conditional branches | 14 | 10 |
| Blocking semantic acceptance heuristics | 3 | 0 |
| Bull prompt characters | 1,368 | 710 |
| Bear prompt characters | 1,368 | 709 |
| Risk prompt characters | 1,365 | 709 |
| Normal fixture serialized agent input | 27,091 bytes | 18,928 bytes |
| Adversarial fixture serialized agent input | 27,505 bytes | 19,764 bytes |

Expected V4 output is approximately 150-350 tokens versus retained earlier V3 attempts of 659-1,337 tokens. This is an estimate, not a V4 live measurement. Active-contract complexity is lower; total repository code necessarily grows because historical versions are preserved. No new provider, agent, indicator or fusion weight was introduced.

## Offline Evidence and Review

- Full relevant offline suite: **392 passed / 0 failed / 1 skipped**. The runner denies external networking; recorded external calls and blocked attempts are zero.
- Normal and adversarial production-sized mocked workflows: **3/3 each**, COMPLETE; cache retrieval, durable status, ledger/attempt details, lineage, fusion, dashboard, pipeline and input immutability checks all pass.
- Invalid ID, role, mode, duplicate, rank/count, schema/snapshot, abstention, malformed JSON/retry, explanation fallback, numerical ownership and exact 48,000/48,001-byte boundary tests pass.
- Existing security, LAN authentication, cross-site/origin, budget, state, pipeline, market/technical/news and historical grounding regressions are included in the offline suite. Security protections were not redesigned or weakened.
- Playwright QA: six A/B desktop, phone and iPad checks pass, including cached reload, rendered chart, overflow, private-content and console checks.
- Native gstack browser QA: the same six cases pass against a loopback synthetic read-only server. No external provider request was made. A phone screenshot was visually checked for card hierarchy, wrapping and separation of canonical facts from explanation.

Installed gstack is **1.91.2.0**, native browser build `01593aa67c94780528e8f5121e47362502410ced`. Scoped review, security and QA instructions/checklists were applied with isolated local telemetry/update/artifact-sync disabled. Native browser QA actually ran. Outside-model specialist review, remote PR/Greptile checks and full infrastructure-wide CSO audit were not run; this offline task does not claim those independent audits. Overall gstack status is therefore PARTIAL, with the available scoped checks passing and no scoped blocker found.

Architecture score **8.8/10**, a custom scoped assessment, not a gstack composite health score: schema authority and truth ownership are clear; structured/prose outcomes are separated; cache/ledger and lineage remain version-safe; malformed output is still rejected. Residual limits are legacy footprint in the existing harness, manually maintained canonical field/freshness rules, lightweight non-entailing optional prose checks, and no V4 live-provider evidence yet. These do not block this offline repair; they prevent a premature all-green live readiness declaration.

## Frozen Future Live Fixtures

| Test | Fixture | Snapshot ID | Input bytes |
| --- | --- | --- | ---: |
| A | synthetic_production_v1_TESTCO | d1a8eba748715245abbbfcb5d28dd5dd773da787b1f2c7b029945f75cb5a0a5b | 18,928 |
| B | synthetic_adversarial_v1_TESTCO | 2bf2f6c97e682ba67746882e47f45a91a02c275577298c09ed2b6467461cb0af | 19,764 |

`v4_final_live_manifest.json` freezes portable fixture files, serialized input hashes, source hashes, prompt/schema/validator/config identities, two workflows, at most twelve calls and fresh authorization requirements. If snapshots expire before authorization, only timestamp refresh with semantic-equivalence proof and a new explicit freeze is allowed before provider execution. Existing budget/provider protections and real-provider cache-miss checks still apply. Nothing in this report executes or pre-authorizes a live workflow.

## Preservation and Stop Boundary

Branch: `monad-metropolis`. The worktree was already dirty; unrelated legitimate changes were preserved. This task changes only the scoped agent/fusion/dashboard integration, version-isolated tests, local audit/QA tooling and V4 artifacts. No commit or push was made.

OpenAI, Yahoo, Tavily, Monad and other external-provider calls: **0**. Kronos inference/training, model-weight changes, scientific validation reruns, locked-test target accesses and trading/blockchain actions: **0**. Historical scientific artifacts and protected model code were not changed. Monad implementation was not started.

**Next action:** Authorize ONE final V4 dual live confirmation: normal + adversarial. Do not run it as part of this task.
