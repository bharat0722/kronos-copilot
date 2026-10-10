# Final Live Test B

**Status: FAIL | Team: 0/3 | Durable state: FAILED**

Fixture: `synthetic_adversarial_v1_TESTCO`
Fresh snapshot: `85a1fc15db5e05d68f78d20b1344a8ad6b0189ac42912c0c5b4804464b6b2138`
Serialized size: 21,834 bytes; maximum: 48,000 bytes.
Semantic/numerical/news/technical/forecast/evidence-family changes: **0**. Production preflight passed; all three caches initially missed.

| Agent | Result | Attempts | Input Tokens | Output Tokens | Provider |
| --- | --- | ---: | ---: | ---: | --- |
| Bear | FAIL | 2 | 22780 | 1518 | completed |
| Bull | FAIL | 2 | 22780 | 1364 | completed |
| Risk | FAIL | 2 | 27848 | 1733 | completed |

## Exact Attempt Rejections

| Agent | Attempt | Stage | Tokens Out | Rejection |
| --- | ---: | --- | ---: | --- |
| bull | 1 | CLAIM_VALIDATION | 565 | FACT requires an exact structured value present in cited evidence: fact_prose_forbidden; unsupported_direct_fact |
| bull | 2 | CLAIM_VALIDATION | 799 | FACT requires an exact structured value present in cited evidence: invalid_state_value; unsupported_direct_fact |
| bear | 1 | CLAIM_VALIDATION | 912 | Interpretation must use interpretive framing and support; unlabelled_interpretation |
| bear | 2 | CLAIM_VALIDATION | 606 | FACT requires an exact structured value present in cited evidence: fact_prose_forbidden; unsupported_direct_fact |
| risk | 1 | CLAIM_VALIDATION | 965 | Claim cites an incompatible evidence type; incompatible_evidence_type |
| risk | 2 | CLAIM_VALIDATION | 768 | FACT requires an exact structured value present in cited evidence: unsupported_field_key; unsupported_direct_fact |

## Gate Results

- cache: PASS
- claim_splitting: FAIL / NOT ACHIEVED
- conflict_preservation: PASS
- durable_state: PASS
- evidence_family: FAIL / NOT ACHIEVED
- fact_interpretation: FAIL / NOT ACHIEVED
- fusion: FAIL / NOT ACHIEVED
- fusion_cache_hit: PASS
- fusion_cache_invalidation: PASS
- immutability: PASS
- ledger: PASS
- mixed_evidence: FAIL / NOT ACHIEVED
- numerical_fact: FAIL / NOT ACHIEVED
- numerical_grounding: FAIL / NOT ACHIEVED
- observability: PASS
- pipeline: PASS
- public_error_safety: PASS
- reference_validation: FAIL / NOT ACHIEVED
- risk_lineage: FAIL / NOT ACHIEVED
- structured_claim: FAIL / NOT ACHIEVED
- support_type: FAIL / NOT ACHIEVED
- traceability: FAIL / NOT ACHIEVED
- truncation: PASS
- uncertainty: FAIL / NOT ACHIEVED
- unit_direction: FAIL / NOT ACHIEVED
- snapshot_isolation: PASS
- production_budget_preserved: PASS
- rejected_outputs_not_cached: PASS

Failure in an end-to-end acceptance gate does not mean every validator independently failed. The saved first rejection identifies the actual failure. All twelve responses parsed and reached typed-claim validation. No response was truncated; all rejected outputs remain uncached.

The failed team state survives normal durable retrieval. Fusion retains missing-agent markers rather than inventing accepted evidence. Adversarial primary conflicts remain visible. A cached primary-only fusion is valid fail-closed behavior, not successful live agent integration.

The initial reporting-only path scanner falsely matched `s:/` inside an ordinary HTTPS source URL. A Windows-path-aware recheck verified no private path, traceback or configured API secret in dashboard-compatible responses. No production sanitization or payload was modified.

Safe attempt metadata includes role run ID, workflow ID, snapshot, prompt/schema, tokens, latency, response status, validation result and cache state. No hidden reasoning or full rejected response is retained. The matching JSON contains the bounded rejected-claim diagnostics.

No production code/configuration/validator/prompt/fixture changes occurred after Test A started. No repair was attempted. No external provider other than OpenAI was called.

## Saved-Result Dashboard Replay

PASS at desktop 1440px, phone 390px and iPad 834px, including reload. All agent cards show Failed; team and pipeline show failed/0 of 3; fusion references the correct snapshot. No overflow, page/console error, secret or private path was observed. Every browser request was fulfilled locally; no POST or external request occurred. This is not a new live LAN or market-chart alignment test.
