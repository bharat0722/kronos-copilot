# Phase 7.3B - Agent Output V2 Typed Claim-Support Contract

**Status:** PASS  
**Phase 7:** COMPLETE  
**Audit #4:** PASS  
**Phase 8 permission:** YES  
**Mode:** Offline implementation and offline testing only

## Decision

Phase 7 closes. The three specialist roles now share one machine-readable `agent_output_v2` claim contract. Facts, numerical facts, interpretations, risks, limitations, uncertainty, comparisons, and forecast interpretations are structurally distinct. Every published material claim preserves snapshot-scoped evidence lineage, except the exact generic directional abstention. Rejected claims fail before publication or success-cache persistence and leave a sanitized attempt diagnostic.

No integrated live regression was run. Phase 7.3A already established successful synthetic live coverage for Bull, Bear, and Risk and found the deterministic aggregator sufficiently covered. The remaining gap was a local schema and validation contract, which is fully testable offline.

## Contract

Every material claim now contains:

- `text`
- `claim_type`
- `support_type`
- `evidence_type`
- `evidence_ids`
- `confidence` on a finite 0-to-1 argument-support scale
- `material=true`

Supported claim types are `FACT`, `NUMERICAL_FACT`, `INTERPRETATION`, `RISK`, `LIMITATION`, `UNCERTAINTY`, `COMPARATIVE`, and `FORECAST_INTERPRETATION`. Support is typed as `DIRECT`, `DERIVED`, `INTERPRETIVE`, `MIXED`, or `INSUFFICIENT`. Evidence is typed as news, technical, forecast, market data, research view, instrument, multi-source, or none.

Bull/Bear arguments, key factors, limitations, and uncertainty use this claim object. Risk factors, conflicts, model/data/event risks, missing evidence, limitations, and uncertainty use the same object. The old uncited side channels are gone.

## Grounding Rules

- A `FACT` requires direct support, a compatible evidence family, non-interpretive wording, and conservative lexical support in the cited structured record.
- A `NUMERICAL_FACT` requires direct support and exact deterministic value, unit, currency where applicable, and semantic field matching.
- An `INTERPRETATION` must be explicitly framed with cautious interpretive language and cite its material premises.
- A `FORECAST_INTERPRETATION` must cite forecast evidence and cannot present model output as realized fact.
- A `COMPARATIVE` claim must cite both compared evidence families.
- Material risk, limitation, uncertainty, and missing-evidence statements require lineage.
- `INSUFFICIENT` cannot support a material claim. It is allowed only for the exact generic directional abstention with no evidence.
- Unsupported advice, instruction-following, unknown IDs, duplicate IDs, incompatible evidence families, and ungrounded numbers fail closed.

The validator deliberately implements practical semantic-grounding Level 4. It does not claim universal natural-language entailment and does not add a paid verifier model.

## Symmetry

`numerical_grounding_v3` applies the same field-aware policy to Bull, Bear, and Risk. Offline tests cover supported and unsupported RSI, forecast percentage, price, currency, and volume claims, including same-valued wrong-field evidence. No role receives a weaker path.

Prompt contracts advanced to:

- Bull: `bull_agent_prompt_v5`
- Bear: `bear_agent_prompt_v4`
- Risk: `risk_agent_prompt_v4`

The model, core roles, tool policy, loop limit, retry limit, and token ceiling did not change.

## Cache And Ledger

Cache identity now includes `agent_output_v2`, prompt version and hash, model, snapshot, `agent_run_v3`, config v3, and both validator versions. Cache records repeat and verify these versions, so v1 output cannot be silently reused.

`agent_run_v3` stores accepted claim type, support type, evidence type, evidence IDs, confidence, material flag, and claim hash. `agent_attempt_v3` stores sanitized rejection type and reason when qualitative or numerical validation fails. Ledger-before-cache remains unchanged. No chain-of-thought is stored.

## Deterministic Aggregation And Dashboard

`AgentTeam.run` remains a dispatcher/aggregator, not a fourth model. It returns specialist reports without synthesizing new financial claims, dropping lineage, or converting interpretations into facts. The dashboard received only a small display adapter: it renders either legacy strings or v2 claim objects, preserving the current layout and product behavior.

## Verification

The relevant offline suite completed:

- **157 passed**
- **0 failed**
- **1 skipped**: the explicitly opt-in live Yahoo regression
- **0 external API calls**

Coverage includes the Phase 7 A-EE closure matrix, shared agent harness, structured response diagnostics, snapshot-scoped evidence IDs, field-aware numerical grounding, Bull-only harness, claim traceability, security hardening, market-data service, news intelligence/impact, product pipeline, cache, ledger, prompt injection, immutable evidence, and default three-agent execution.

Python syntax and JavaScript syntax checks passed in the writable verification copy. No forecast calculation, scientific result, validation membership, or locked-test artifact was changed.

## Accepted Limitations

- No independent semantic-verifier model.
- Confidence is argument support, not forecast probability or accuracy.
- No model-based orchestrator.
- Detailed diagnostics remain local only.
- Cancellation remains bounded by timeout and budget rather than browser interruption.
- Conservative lexical checking may abstain or reject a valid paraphrase; failing closed is intentional.

## Safety Accounting

- OpenAI calls: 0
- Other LLM calls: 0
- Tavily calls: 0
- Kronos inference: 0
- Kronos training: 0
- Model-weight changes: 0
- Validation reruns: 0
- Locked-test accesses: 0
- Agent tools: NONE
- Loop limit: 1
- Retry limit: 1 per failed agent

## Closure

The Phase 7 blockers identified in Phase 7.3A are closed. Phase 8 may begin, provided its Evidence Fusion contract consumes `agent_output_v2`, defines deterministic Risk veto/abstention and partial-team behavior, and preserves the existing evidence, cost, privacy, and execution boundaries.
