# V3 Live Test A

Status: FAIL

Synthetic fixture: synthetic_production_v1_TESTCO
Snapshot: 61380f35849860c6ed45b1bb42d0032673325673ff839e7322bff6c88c3986e3
Input bytes: 27091
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
| bull | 1 | FAILED | 9957 | 728 | 10685 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| bull | 2 | FAILED | 9957 | 962 | 10919 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| bear | 1 | FAILED | 9957 | 1130 | 11087 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| bear | 2 | FAILED | 9957 | 1054 | 11011 | SCHEMA_VALIDATION | Agent v3 schema validation failed |
| risk | 1 | FAILED | 9954 | 708 | 10662 | CLAIM_VALIDATION | Agent v3 evidence contract failed |
| risk | 2 | FAILED | 9954 | 905 | 10859 | CLAIM_VALIDATION | Agent v3 evidence contract failed |

Production ledgers are unchanged. Supplemental workflow ledger adds test/workflow IDs and source hashes.
Only accepted structured outputs are retained; raw provider response/hidden reasoning is not persisted.
A false success-gate check means the accepted-team contract was not met; it does not prove every individual schema/reference check failed. Failed states persisted correctly and no failed success cache exists.
No code, prompt, validator, fixture or financial fusion rule changed during execution. No other provider called.
