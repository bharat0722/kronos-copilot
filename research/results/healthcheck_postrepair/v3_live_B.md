# V3 Live Test B

Status: FAIL

Synthetic fixture: synthetic_adversarial_v1_TESTCO
Snapshot: e936ae78ecb593b419c841e5446047b284bb62d4ea7480df1ced97c9bb21958f
Input bytes: 27505
Semantic evidence differences: 0
Team accepted: 0/3

## Checks

- backend_rendering: FAIL
- cache: FAIL
- conflicts: PASS
- dashboard_adapter: FAIL
- durable: FAIL
- fact_references: FAIL
- families: FAIL
- fusion_adapter: FAIL
- fusion_cache_invalidation: FAIL
- fusion_health: PASS
- fusion_lineage: FAIL
- fusion_missing_agents: FAIL
- immutability: PASS
- interpretation_contract: FAIL
- no_model_numbers: FAIL
- observability: PASS
- pipeline: FAIL
- public_error_safety: PASS
- references: FAIL
- risk_lineage: FAIL
- schema: FAIL
- snapshot_ownership: PASS
- stance: FAIL
- team: FAIL
- traceability: FAIL
- truncation: PASS
- uncertainty: FAIL

## Attempts

| Agent | Attempt | Status | Input | Output | Total | Failure stage | Reason |
|---|---:|---|---:|---:|---:|---|---|
| bull | 1 | FAILED | 9983 | 953 | 10936 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| bull | 2 | FAILED | 9983 | 1012 | 10995 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| bear | 1 | FAILED | 9983 | 832 | 10815 | NUMERICAL_GROUNDING | Model-authored numbers are forbidden |
| bear | 2 | FAILED | 9983 | 1105 | 11088 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| risk | 1 | FAILED | 9980 | 1407 | 11387 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| risk | 2 | FAILED | 9980 | 931 | 10911 | CLAIM_VALIDATION | Agent v3 evidence contract failed |

Production ledgers are unchanged. Supplemental workflow ledger adds test/workflow IDs and source hashes.
Only accepted structured outputs are retained; raw provider response/hidden reasoning is not persisted.
A false success-gate check means the accepted-team contract was not met; it does not prove every individual schema/reference check failed. Failed states persisted correctly and no failed success cache exists.
No code, prompt, validator, fixture or financial fusion rule changed during execution. No other provider called.
