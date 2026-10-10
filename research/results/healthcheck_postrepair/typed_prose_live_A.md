# Typed-Prose V3 Live Test A
Status: FAIL
Fixture: synthetic_production_v1_TESTCO
Snapshot: 09f840d4349ba850e0bc0e938fcbb0c2aab5e571b473e572c337115dfbbe3426
Serialized input: 27091 bytes
Semantic differences: 0
Team: 0/3

## Checks
- backend_rendering: NOT MET
- cache: NOT MET
- conflicts: PASS
- dashboard_adapter: NOT MET
- durable: NOT MET
- fact_references: NOT MET
- families: NOT MET
- fusion_adapter: NOT MET
- fusion_cache_invalidation: NOT MET
- fusion_health: PASS
- fusion_lineage: NOT MET
- fusion_missing_agents: NOT MET
- hedge_not_required: PASS
- immutability: PASS
- interpretation_contract: NOT MET
- no_model_numbers: NOT MET
- observability: PASS
- pipeline: NOT MET
- precise_rejection_diagnostics: PASS
- public_error_safety: PASS
- references: NOT MET
- risk_lineage: NOT MET
- schema: NOT MET
- snapshot_ownership: PASS
- stance: NOT MET
- team: NOT MET
- traceability: NOT MET
- truncation: PASS
- uncertainty: NOT MET

## Per-attempt usage and rejection detail
| Agent | Attempt | Result | Input | Output | Total | Provider | Rule | Location |
|---|---:|---|---:|---:|---:|---|---|---|
| bull | 1 | FAILED | 9957 | 741 | 10698 | completed | deterministic_fact_in_prose | $.arguments[2].interpretation.text |

Sanitized excerpt: 'The forecast implies a modest change relative to the last observed price while the market data quality is reported as passing; this suggests the signal exists but that the magnitude and realization remain uncertain.'; reason: deterministic fact in prose.

| bull | 2 | FAILED | 9957 | 709 | 10666 | completed | unsupported_directional_conflict | $.arguments[2].stance |

Sanitized excerpt: 'MIXED'; reason: unsupported directional conflict.

| bear | 1 | FAILED | 9957 | 718 | 10675 | completed | unsupported_directional_conflict | $.arguments[0].stance |

Sanitized excerpt: 'MIXED'; reason: unsupported directional conflict.

| bear | 2 | FAILED | 9957 | 736 | 10693 | completed | unsupported_directional_conflict | $.arguments[0].stance |

Sanitized excerpt: 'MIXED'; reason: unsupported directional conflict.

| risk | 1 | FAILED | 9954 | 1295 | 11249 | completed | unsupported_directional_conflict | $.arguments[0].stance |

Sanitized excerpt: 'MIXED'; reason: unsupported directional conflict.

| risk | 2 | FAILED | 9954 | 890 | 10844 | completed | schema_string | $.arguments[0].interpretation.text |

Sanitized excerpt: 'Model direction and technical trend align with a positive orientation, while recent company messaging includes a single product partnership event characterized as supportive but not decisive. Together this suggests contextual bullish signal'; reason: schema string.


No rejected output is published or accepted into success cache. No hidden reasoning or raw provider response is stored.
Production code, schemas, prompts, validators, fixtures and fusion rules remained frozen. Paid work used only synthetic NSE:TESTCO.
