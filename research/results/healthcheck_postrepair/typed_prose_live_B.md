# Typed-Prose V3 Live Test B
Status: FAIL
Fixture: synthetic_adversarial_v1_TESTCO
Snapshot: 186008d17083fde808636cc09f57b83122255cf33796cfb026ce357317e3f0b8
Serialized input: 27505 bytes
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
| bull | 1 | FAILED | 9980 | 789 | 10769 | completed | deterministic_fact_in_prose | $.limitations[2].text |

Sanitized excerpt: 'Technical regime is described as elevated volatility, which reduces the reliability of short-term directional signals.'; reason: deterministic fact in prose.

| bull | 2 | FAILED | 9980 | 1150 | 11130 | completed | missing_or_duplicate_evidence | $.uncertainty[1].evidence_ids |

Sanitized excerpt: 'News relevance and quality support the positive announcement but do not quantify likely price effect.'; reason: missing or duplicate evidence.

| bear | 1 | FAILED | 9980 | 717 | 10697 | completed | deterministic_fact_in_prose | $.uncertainty[0].text |

Sanitized excerpt: 'The balance between model-driven upside and technical downside is unresolved; interpretation may change as new price or reported outcomes appear.'; reason: deterministic fact in prose.

| bear | 2 | FAILED | 9980 | 659 | 10639 | completed | missing_or_duplicate_evidence | $.arguments[1].interpretation.evidence_ids |

Sanitized excerpt: 'News coverage appears weak or unconfirmed on key items, which may provide limited bullish support and leaves the outlook vulnerable to technical downside.'; reason: missing or duplicate evidence.

| risk | 1 | FAILED | 9977 | 1337 | 11314 | completed | unsupported_directional_conflict | $.arguments[0].stance |

Sanitized excerpt: 'MIXED'; reason: unsupported directional conflict.

| risk | 2 | FAILED | 9977 | 768 | 10745 | completed | field_not_in_cited_evidence | $.arguments[2].evidence_fact_refs[1] |

Sanitized excerpt: 'The market regime and research view indicate elevated volatility and identified primary risks; this suggests increased uncertainty and higher risk around short-term outcomes.'; reason: field not in cited evidence.


No rejected output is published or accepted into success cache. No hidden reasoning or raw provider response is stored.
Production code, schemas, prompts, validators, fixtures and fusion rules remained frozen. Paid work used only synthetic NSE:TESTCO.
