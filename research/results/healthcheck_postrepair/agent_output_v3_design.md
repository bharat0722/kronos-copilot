# Agent Output V3 - Evidence-Native Claim Architecture

## Decision and Scope

The architectural repair passes offline. Bull, Bear and Risk are GREEN OFFLINE;
the AI Research Team remains YELLOW PENDING LIVE V3 CONFIRMATION. Monad permission
remains NO. This task made no external provider/model call, inference, training,
validation evaluation, trading action, commit or push. It did not read locked-test
targets. Historical v2/v2_1 artifacts remain historical evidence, not v3 successes.

## Observed Root Cause

The two latest live workflows completed twelve provider attempts with no accepted
agent output. Their first-failing conditions were five fact-prose errors, two
state/direction errors, two numerical-prose binding errors, one interpretive support
error, one evidence-family error and one missing structured fact key. The provider,
serialization and output ceiling were working. Earlier completed live workflows
exhibited the same ownership problem: models reproduced deterministic facts while
validators tried to recover their intended meaning.

`v3_live_failure_replay.json` reconciles twenty-four retained rejected attempts from
the successive confirmation runs and ledgers. It preserves original diagnostics
and source hashes. Its corrections are offline-authored structural equivalents,
not regenerated model outputs or reconstructions of discarded full responses.
Historical API failures without claim diagnostics are not invented as claim cases.

## Responsibility Boundary

EvidenceSnapshotV1 -> existing evidence catalog -> canonical fact-reference catalog
-> bounded agent -> strict v3 validation -> backend fact rendering -> durable ledger
-> accepted cache/publish -> dashboard and derived-evidence fusion adapters.

`app/agent_output_v3.py` is the shared contract for all roles. An EvidenceFactRef has
exactly `evidence_id` and `field_key`. No model value, unit, factual direction or
field alias is accepted. Exact existing `field_bindings` are reused. Model identity
and forecast horizon are resolved from existing forecast metadata. Source-family
identity comes from the backend. Unavailable, non-finite, incorrectly typed or
sensitive fact sources are rejected; absence is not converted to neutral.

The deterministic renderer preserves raw source values and references. Percentage
signs remain unchanged. Prices use native quote units, never inferred INR/USD.
Production news-quality labels remain categorical states; synthetic numeric
source-quality scores remain unitless. Rendering never promotes either to a
statistical probability.

## Model Contract

Current schema: `agent_output_v3`. Shared validator: `evidence_native_grounding_v1`.
Renderer: `canonical_fact_renderer_v1`. Bull v9, Bear v8 and Risk v8 select facts
and supply number-free INTERPRETATION / INTERPRETIVE text. Stance and qualitative
support use explicit enums. Fact references and interpretations are separate.
Interpretations may cite multiple valid families without a model-declared fake
single family. Each referenced fact must appear in interpretation lineage.

All roles use the same validator. Role-compatible stances are enforced; a bullish
case cannot rely only on bearish evidence. A directional conflict requires both
directions. Unsupported conclusions, unknown enums, invalid source/field pairs,
missing citations, invented event assertions, model numbers, unsafe instructions
and advice fail closed. Bull/Bear have at most three arguments; Risk at most four.
Limitations and uncertainty remain visible and cited. Abstention is permitted.

This is bounded deterministic grounding, not universal semantic entailment. Cautious
interpretive language is explicitly not a verified fact. An independent verifier
model was neither added nor called. No accuracy claim or calibrated probability is
established by this repair.

## Harness, Persistence and Compatibility

The production harness exclusively validates v3. Responses API and
`client.responses.create` remain unchanged, with strict closed JSON schemas and
snapshot-specific enums. Existing response/refusal/incomplete/usage diagnostics
remain in place. Model gpt-5-mini, input maximum 48,000 bytes, output maximum 1,600
tokens, loop one, retry one per failed role, tools NONE and daily cap twelve remain
unchanged. SDK retries are still disabled.

Cache identity includes model, snapshot, role, prompt version/hash, schema and
validator versions. v2/v2_1 caches cannot satisfy production v3. Per-attempt and
parent ledgers retain schema/prompt versions and exact claim-reference hashes.
Validation precedes durable ledger, then cache/publication. A verified v3 cache-write
failure now prevents publication and records CACHE_WRITE, avoiding a misleading
COMPLETE state that disappears on reload. No extra provider retry is performed.

Historical contract tests use `research/tests/legacy_agent_harness.py`, a test-only
adapter preserving old validators, serialization and diagnostic expectations. No
application imports it. This adapter is not evidence of v3 acceptance. Native v3
tests use the unmodified production AgentTeam boundary with mocked Responses clients.
Both populations remain in the offline runner, with external sockets/DNS blocked.

## Fusion and Dashboard

The adapter retains Bull/Bear/Risk as DERIVED evidence with no primary-direction
contribution. Individual run IDs, snapshot IDs, fact references and interpretation
citations survive. Risk interpretations reach the existing risk list. Wrong-snapshot,
invalid v3 and unknown-schema reports cannot influence fusion through a risk-only
side path. Existing financial weights and evidence_fusion_v1 rules remain unchanged.
V3 adapter identity is included only for v3 caches; historical cache-key construction
is otherwise preserved.

Existing agent cards display backend fact strings separately from interpretations,
with qualitative support and visible limitations/uncertainty. textContent is used;
model text is never executed or rendered as HTML. No dashboard redesign was made.
`v3_qa/qa.json` records desktop 1440px, phone 390px and iPad 834px checks for both
cases and cached reloads. All traffic was intercepted locally. This is scoped
agent/fusion/pipeline display QA, not proof of live market/news alignment or LAN reachability.

## Validation and Review

Final offline suite: 299 passed, zero failed/errors and one skipped (300 total),
including 46 native v3 tests. The skipped case is the existing opt-in live Yahoo
regression. `v3_offline_tests_verified.json` records zero external calls and zero
blocked external attempts. `v3_offline_A.json` / `v3_offline_B.json` retain native
complete-team proofs. Tests were not repeated during final artifact closeout.
The fixtures retain twelve indicators, eight articles/events and all existing
families. Exact new production wire sizes are 27,091 and 27,505 bytes; extra bytes
are the canonical ID/key pair catalog, not padded narrative. Both are below 42,000
and the unchanged 48,000 maximum. Native tests exercise exactly 48,000 eligibility
and 48,001 rejection. Output estimates in the manifest are byte-based heuristics,
not measured token use or a guarantee against future truncation.

Installed gstack review, CSO AI-boundary and qa-only checklists were applied. Native
workflow status is PARTIAL: a browse build is present, but current skills require
Aside and no Aside/Bash command is available. No install, upgrade, telemetry,
outside-model review or external documentation request occurred. Local scoped
review/security checks and Playwright fallback QA pass. Full dependency/CVE scanning,
full CSO secrets archaeology and live provider/LAN validation are outside this scope.

Custom scoped architecture score: 8.6/10, not a gstack composite score. Fact ownership
is materially simpler and shared across roles; existing broad harness/server ownership
and retained legacy compatibility offset that improvement. No new provider, god
module, duplicated role validator, tool authority or financial fusion algorithm was
introduced. There is no actionable offline blocker in this repair; live compliance
is explicitly unproven.

## Frozen Future Validation

`v3_live_retest_manifest.json` pins fixture/snapshot/wire/source hashes, versions,
budgets and separate future-live cache namespaces. Mock accepted caches must never
serve as provider evidence. New explicit authorization, sufficient persisted daily
allowance and the unchanged one-hour freshness guard are prerequisites. Expired
fixtures require a separately authorized timestamp-only freeze; never silently
refresh hashes or reset the production budget.

Next action: Authorize two fresh live v3 Agent Team tests: normal + adversarial.
Do not execute them as part of this task. Monad development remains blocked on
successful bounded live confirmation.
