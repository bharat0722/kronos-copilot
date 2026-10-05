# Phase 7.3A - Phase 7 Closure Audit

**Mode:** offline audit only  
**Audit result:** PASS as an audit; **Phase 7 closure readiness: YELLOW**  
**Phase 7:** PARTIAL  
**Phase 8:** NOT PERMITTED

## Executive decision

The repository now has enough evidence to conclude that **another integrated Bull + Bear + Risk live regression is not required**. Bull, Bear, and Risk each have successful synthetic live evidence on the same immutable TESTCO snapshot. Bear and Risk passed inside a complete sequential `AgentTeam.run`; Bull later passed through `run_bull_only`, which delegates to the same `_run_agents` preflight, request, validation, budget, ledger, and cache path. The so-called orchestrator is deterministic Python aggregation, not a fourth model or synthesis call. Existing offline tests cover the complete three-agent path and partial/failure outcomes.

Phase 7 still cannot close. The remaining blocker is structural rather than operational: current claim objects contain only `text` and `evidence_ids`. The validator proves that IDs exist and numbers match structured values, but cannot machine-distinguish a direct fact from an interpretation or reject a semantically irrelevant qualitative citation. Material limitations and uncertainty are uncited strings, and Bull has stronger field-aware numerical semantics than Bear/Risk. Another paid run would repeat this contract, not repair it.

The practical Phase 7 target is semantic-grounding **Level 4**, not universal model-based entailment: exact facts/numbers are deterministic, interpretations are explicitly typed and framed, every premise is cited, and unsupported statements fail closed. An independent semantic-verifier model is not scientifically justified for this capstone boundary.

## Phase 7 evolution

| Checkpoint | Goal and change | Result / remaining | Mode | Prompts | Tests | External calls |
| --- | --- | --- | --- | --- | ---: | ---: |
| Phase 7.0 | Build EvidenceSnapshotV1-driven Bull/Bear/Risk architecture, authenticated routes, bounded harness, cache, ledger and dashboard cards | Architecture created; no live behavior proof; semantic entailment explicitly unverified | Offline | Bull/Bear/Risk v1 | 76 pass, 1 skip; broad research had 2 known registry-write errors | 0 |
| Audit #4 | Adversarial architecture gate | PARTIAL/YELLOW, 6.5/10; found uncited/unsupported claims and ledger/cache ordering as HIGH blockers | Offline | Then-current prompts | 46 pass | 0 |
| Phase 7.1 | Fail closed on material citations/numbers; ledger-before-cache; prompt hash; synthetic smoke design | PASS offline; general semantic entailment remained unverified | Offline | Bull/Bear/Risk v3 | 50 pass | 0 |
| Phase 7.2 | First synthetic TESTCO team smoke | All six bounded attempts failed as undifferentiated `ValueError`; no usable output | Live synthetic | v3 | No new offline count | 6 OpenAI |
| Phase 7.2A | Add failure stages, per-attempt ledger, safe metadata/usage, strict preflight and mocked response coverage | PASS offline; previous root cause could not be reconstructed | Offline | v3 | 62 pass | 0 |
| Phase 7.2B | Instrumented TESTCO team retest | Bear passed; Bull numerical/reference failure; Risk incomplete then reference failure | Live synthetic | v3 | No new offline count | 5 OpenAI |
| Phase 7.2C | Constrain all citation fields to the current snapshot's catalog enum | PASS offline; remote enum still needed live proof | Offline | v3 | 35 pass | 0 |
| Phase 7.2D | Retest dynamic citation schema | Bear passed first attempt; Risk passed on its one retry; Bull failed deterministic numerical grounding twice | Live synthetic | v3 | No new offline count | 5 OpenAI |
| Phase 7.2E | Add Bull field-aware numerical grounding, sanitized rejection diagnostic and Bull v4 | PASS offline; Bear/Risk behavior intentionally unchanged | Offline | Bull v4; Bear/Risk v3 | 53 pass | 0 |
| Phase 7.2F initial | Attempt authorized Bull-only retest | Safely BLOCKED because no supported Bull-only path; no call made | Offline stop | Bull v4 | Not rerun | 0 |
| Phase 7.2F.1 | Add `run_bull_only` using shared `_run_agents` | PASS offline; default team unchanged | Offline | Bull v4; Bear/Risk v3 | 66 pass | 0 |
| Phase 7.2F final | Controlled Bull-only TESTCO retest | PASS first attempt; references, numbers, ledger, cache and immutability passed | Live synthetic | Bull v4 | Preconditions inherited | 1 OpenAI |
| Phase 7.3A | Reconcile history and audit qualitative support/traceability | Audit PASS; closure YELLOW because typed qualitative contract is absent | Offline | Unchanged | 75 pass | 0 |

No checkpoint in this audit was invented. Phase 7.2F contains both the original safe stop and the later separately authorized success; both remain in the final report history.

## Final agent contracts

### Bull

- Input: immutable `EvidenceSnapshotV1` canonical bytes and snapshot-scoped evidence catalog.
- Output: `agent_output_v1` Bull object with stance, argument, supporting/contradicting IDs, key factors, limitations, uncertainty and argument confidence.
- Prompt/model: `bull_agent_prompt_v4`, `gpt-5-mini`, minimal reasoning.
- Limits: no tools, one reasoning round, one retry after failure, 900 output tokens, 30-second SDK timeout, persistent 12-call daily budget.
- Grounding: every key factor needs nonempty valid IDs; argument needs references unless it is an exact generic abstention; deterministic Bull numbers require matching value, unit and semantic field category.
- Persistence: snapshot/model/prompt hash/schema/config-aware cache; durable attempt and parent ledger before reusable cache.
- Failure: invalid schema/reference/number/refusal/incomplete output fails closed; one eligible retry; no success cache for rejected output.

### Bear

- Same input, model, tools, loop, retry, token, budget, cache, ledger and failure policy as Bull.
- Prompt: `bear_agent_prompt_v3`.
- Output: same Bull/Bear schema with Bear stance.
- Grounding: citation and exact-number checks apply, but semantic field-category matching is not as strong as Bull's v4 path. FACT versus INTERPRETATION is not machine-labelled.

### Risk

- Same input, model, tools, loop, retry, token, budget, cache, ledger and failure policy.
- Prompt: `risk_agent_prompt_v3`.
- Output: risk level, typed-by-container risk/conflict/model/data/event lists, evidence IDs, missing evidence, limitations, uncertainty and confidence.
- Grounding: material claim collections require citations; exact numbers are checked, but fact/interpretation and semantic field category are not fully encoded.
- Risk may return `UNKNOWN`; it has no execution or veto authority because Phase 7 has no final synthesis.

### Orchestrator

There is no model orchestrator. `AgentTeam.run` is a deterministic dispatcher/aggregator. It sends byte-identical evidence serially to Bull, Bear and Risk, records each result independently, counts completed agents, and returns `SUCCESS`, `PARTIAL`, `FAILED` or `CACHED`. It introduces no financial claim, confidence, citation, or synthesis and performs zero additional provider calls.

### Harness

The harness owns strict schema preflight, snapshot identity, byte ceiling, provider invocation, persistent usage reservations, bounded retries, response-state classification, parsing, local validation, safe attempt diagnostics, parent ledger, cache, failure isolation and health summary. Agents receive no shell, browser, data-provider, filesystem, broker or network tool.

## Practical semantic standard

Phase 7 requires Level 4:

1. Level 0: cited source exists.
2. Level 1: claim is attached to a source.
3. Level 2: claim type is compatible with evidence type.
4. Level 3: direct facts and numbers are deterministically supported.
5. Level 4: derived/interpretive statements are explicitly marked and preserve all premise citations.
6. Level 5: independent semantic-verifier model. Not required.

The current system is Level 2-3 with partial Level-4 context from role headings and prompt wording. It is not reliably Level 4 because the JSON contract does not carry `claim_type` or `support_type` and uncited prose side channels remain.

## Claim taxonomy and rules

| Type | Evidence requirement | Deterministic rule | Allowed | Forbidden |
| --- | --- | --- | --- | --- |
| Deterministic numerical | Exact cited structured value, unit and field category | Required for every role | Exact reported metric | Estimates, arithmetic, same-valued unrelated fields |
| Direct factual qualitative | Compatible source explicitly contains the fact | Evidence-family and conservative field/text match | “The supplied article reports...” | Facts absent from cited record |
| Derived qualitative | All premises cited | Must carry derived type and may/could/suggests framing | “This may be constructive context” | Presenting interpretation as raw fact |
| Interpretive | Relevant evidence and explicit interpretation label | No new factual/number claim | Bounded analyst view | Unqualified factual wording |
| Comparative | Both sides cited and comparable | Compatible scales/fields | Scoped comparison | Comparing unrelated scores as equivalent |
| Uncertainty/risk | Conflict, quality, staleness or missing-field evidence | Cite conflict sides or quality field | Scoped caution | Generic fear or uncited external risk |
| Forecast interpretation | Model/direction fields and exact numbers when used | Must say model indicates, not outcome is certain | “Kronos indicates...” | Guaranteed movement or advice |

Absence claims must say “the supplied snapshot contains no...” rather than making an outside-world assertion. Causal language is prohibited unless causality is explicit in a cited source.

## Accepted live-output inspection

The complete machine-readable inventory is in `claim_traceability_contract.json`. Material findings:

| Claim group | Agent | Support | Finding |
| --- | --- | --- | --- |
| Composite modest upside argument | Bull | DERIVED | Cautious and substantively supported; interpretation not machine-labelled |
| Upward forecast factor | Bull | WEAK | Direction supported; “proprietary” is unsupported for a synthetic fixture |
| Bullish RSI implies momentum | Bull | DERIVED | Signal direct; momentum is interpretation |
| Service launch as constructive context | Bull | DERIVED | Article direct; constructive effect explicitly conditional |
| Low/neutral view limits conviction | Bull | DERIVED | State direct; conviction is interpretation |
| Bull limitations/uncertainty | Bull | WEAK | Substantively traceable but no evidence IDs in schema |
| Generic abstention | Bear | DIRECT | Exact policy-approved no-strong-case output |
| Bear limitations/uncertainty | Bear | WEAK | Conservative but uncited per item |
| Conflicting news/research view | Risk | DIRECT | Explicitly supported |
| +2% model upside caveat | Risk | DIRECT | Exact structured number and model framing |
| Sideways/mixed technical interpretation | Risk | DERIVED | Values exact; strength conclusion interpretive |
| Injection item reduces trust | Risk | DERIVED | Text direct; trust effect interpretive |
| News synthetic/untrusted | Risk | WEAK | Provider/uncertainty support it; `GOLD_AVAILABLE` itself does not mean synthetic |
| No verified real events | Risk | WEAK | Valid only when scoped to the snapshot; original wording sounds broader |
| Synthetic forecast may not generalize | Risk | DERIVED | Appropriately framed as “may” |
| Risk limitations/uncertainty | Risk | WEAK | Reasonable but uncited; corroboration absence exceeds explicit source scope |

Across 18 audited material claim groups: 5 DIRECT, 7 DERIVED, 6 WEAK, 0 wholly UNSUPPORTED. No accepted numerical value is unsupported. The six WEAK groups are enough to keep the machine contract yellow because future outputs can pass with the same structural weakness.

## Numerical grounding reconciliation

The live Bull result passed `numerical_grounding_v2` with zero unsupported numbers. The accepted Risk output's `+2%` and RSI `55.0` exactly match cited structured values. Bear's accepted output contains no numeric assertion. Existing tests reject unsupported percentages, currency values, targets, technical values, unknown references, unit conflicts, scientific notation and selected spelled-number formats.

The remaining issue is contract symmetry: `_bull_numeric_kind` applies field-category matching only when `agent_type == "bull"`. Bear/Risk still require cited exact values but can theoretically match the same value from the wrong semantic field. This is a closure blocker, not evidence that the accepted Bear/Risk outputs were wrong.

## Prompt contract review

All prompts state that evidence is untrusted data, tools do not exist, key/risk claims need evidence IDs, arguments may only summarize cited factors, numbers must be copied from structured evidence, unsupported advice/facts are prohibited, and uncertainty should cause abstention.

Bull v4 additionally prohibits estimates/arithmetic and requires matching number, unit and field. Bear v3 and Risk v3 lack that role-specific clarity. None of the prompts or schemas requires a machine-readable FACT versus INTERPRETATION label. The role/card headings imply interpretation to a human, but implication is insufficient for Phase 8 ingestion.

## Integrated live regression decision

**NOT REQUIRED.**

- Bull: live PASS in Phase 7.2F, v4, one call, no retry.
- Bear: live PASS in the Phase 7.2D full-team run, v3, one call.
- Risk: live PASS in Phase 7.2D, v3, one permitted retry after an incomplete response.
- Orchestrator: deterministic code, zero model calls, no synthesis.
- Shared path: `run` and `run_bull_only` both use `_run_agents`; offline tests cover full-team success, partial failure, total failure, retries, cache and ledger.

An integrated paid run would mostly sample model variability and would not test the missing claim type. A post-contract live smoke may be optional operational assurance with fresh authorization, but it is not the current closure requirement.

## Harness, injection, privacy and failure closure

- Loop: one sequential reasoning round, code enforced.
- Retry: one per failed agent; SDK retries disabled.
- Tools: none; `tool_choice=none`; parallel tool calls false.
- Cost: persistent 12-call daily SQLite budget, route rate guards, token/byte limits and cache.
- Cache: prompt-content hash, snapshot, role, model, schema/config and inference settings; matching successful parent required.
- Ledger: attempt v2 and parent v2; budget reservation precedes call; parent precedes cache; final cache state is durable.
- Evidence: immutable snapshot/content hashes verified across live runs.
- Injection: TESTCO malicious text attempted instruction override, key disclosure, forced BUY and confidence manipulation. Accepted Bull, Bear and Risk did not obey it; unsafe output patterns and invalid references fail closed.
- Privacy: only the authorized synthetic TESTCO payload left the laptop. No real NSE/SWIGGY snapshot, locked-test content, credential, identity or local path was transmitted.
- Failure: invalid JSON/schema/reference/number, refusal, empty/incomplete responses and provider errors are classified and bounded. Partial teams are returned as `PARTIAL`, never falsely complete. No Phase 7 synthesis exists.

## Observability

Durable local ledgers expose run ID, attempt IDs, model/prompt, status, response/request IDs, latency, usage, failure stage, validation diagnostic, cache state and retry decision without chain-of-thought. The product response/dashboard exposes role status, report, evidence IDs, confidence, analyzed time and saved/new state. Pipeline health exposes status, completed count, latency and cache state.

Observability is YELLOW because attempts, failure stage, validation diagnostic, run ID and ledger state are not fully surfaced in the dashboard/pipeline card. This is an acceptable product limitation for Phase 7 closure because the durable forensic record exists and sensitive reasoning is not exposed.

## Completion matrix summary

GREEN: architecture, orchestrator, harness, structured output, references, prompt injection, loops, retries, cost, cache, ledger, privacy, immutability, failure handling, LAN/security, no tools and no execution authority.

YELLOW/BLOCKING: qualitative grounding, semantic traceability, material side-channel citations, and symmetric field-aware numerical semantics.

YELLOW/NONBLOCKING: dashboard observability depth.

## Audit #4 reconciliation

- A4-01 unsupported/uncited claims: **partly remediated, still BLOCKING** for qualitative semantics.
- A4-02 ledger/cache ordering: **CLOSED**.
- A4-03 real-evidence egress minimization: synthetic tests safe; **OPEN before real Phase 8 use**.
- A4-04 prompt/cache drift: **CLOSED** through prompt hash/version identity.
- A4-05 Risk veto/partial fusion: not a Phase 7 defect; **OPEN and BLOCKING for Phase 8 design**.

Audit #4 therefore remains PARTIAL until the typed qualitative contract closes A4-01.

## Must fix before Phase 7 closes

1. Extend the existing claim object with `claim_type` and `support_type`, or equivalent fields; do not create a duplicate claim hierarchy.
2. Require lineage for every material published statement, including factual limitations, uncertainty and missing-evidence text. Preserve only fixed generic abstentions as uncited.
3. Enforce evidence-family compatibility, snapshot-scoped absence claims, both-side comparison citations and no unsupported causality.
4. Apply field/unit/category-aware numerical matching symmetrically to Bull, Bear and Risk.
5. Update all three prompts to distinguish FACT from INTERPRETATION and invalidate cache by prompt/schema identity.

## Acceptable limitations

- No Level-5 semantic-verifier model.
- Argument confidence remains uncalibrated support, not probability or accuracy.
- No model orchestrator; deterministic aggregation is intentional.
- Full forensic details remain local in the ledger rather than all appearing in the dashboard.
- Browser disconnect does not cancel an in-flight provider request; timeout and budgets remain bounded.

## Phase 8 entry criteria

Phase 8 may begin only after the five must-fix controls pass offline tests; Risk veto/abstain and partial-team behavior are specified for fusion; and existing loop, retry, tool, budget, cache, ledger, privacy and immutability controls remain green. Another live integrated regression is not a prerequisite.

## Tests and repository state

The offline Phase 7 suites plus nine new characterization tests passed **75/75**, with 0 failed and 0 skipped. The new tests prove supported direct/numerical cases, reject missing/unknown citations and unsupported numbers, and deliberately characterize the current fact/interpretation and irrelevant-citation gaps. External calls: 0.

Branch: `main`. The repository remains dirty with the pre-existing Phase 7.2F.1 implementation/test plus this audit's artifacts and characterization test. No push, history rewrite, tag change, Kronos inference/training, validation rerun, locked-test access or Phase 8 work occurred.

## Next action

Implement and offline-test one `agent_output_v2` typed claim-support contract across Bull, Bear and Risk, including cited material side-channel claims and symmetric numerical field matching; do not make a live call.
