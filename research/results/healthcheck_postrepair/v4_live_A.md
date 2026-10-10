# V4 Live Test A

Status: PASS
Fixture: synthetic_production_v1_TESTCO
Snapshot: a6c32860edf620e87a34b112fb735a5ebef48eb19400893b031b5db9fc054f63
Serialized bytes: 18928
Semantic differences: 0
Team: 3/3

## Checks
- backend_conflict: PASS
- backend_direction: PASS
- backend_fact_resolution: PASS
- backend_uncertainty: PASS
- cache: PASS
- conflict_preservation: PASS
- dashboard_adapter: PASS
- double_counting: PASS
- durable: PASS
- evidence_ids: PASS
- fusion_adapter: PASS
- fusion_cache_invalidation: PASS
- fusion_health: PASS
- immutability: PASS
- ledger: PASS
- lineage: PASS
- missing_agent_markers: PASS
- no_truncation: PASS
- observability: PASS
- optional_prose_nonblocking: PASS
- pipeline: PASS
- public_error_safety: PASS
- role_admissibility: PASS
- snapshot_ownership: PASS
- structured: PASS
- team: PASS

## Attempts
| Agent | Attempt | Structured | Explanation | Input | Output | Total | Provider | Rejection |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |
| bull | 1 | SUCCESS | VALID_UNVERIFIED | 5998 | 178 | 6176 | completed | - |
| bear | 1 | SUCCESS | VALID_UNVERIFIED | 5998 | 182 | 6180 | completed | - |
| risk | 1 | SUCCESS | VALID_UNVERIFIED | 6000 | 192 | 6192 | completed | - |

## Backend and Optional Prose
[
  {
    "action": "PRESENT_CASE",
    "agent": "bull",
    "conflict": false,
    "direction": "BULLISH",
    "explanation_status": "VALID_UNVERIFIED",
    "local_nonblocking_probes": [
      {
        "explanation": "REJECTED",
        "kind": "number",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "OMITTED",
        "kind": "empty",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      }
    ],
    "selected": [
      {
        "evidence_id": "kronos.direction",
        "priority": 1,
        "use": "SUPPORT"
      },
      {
        "evidence_id": "technicals.trend",
        "priority": 2,
        "use": "SUPPORT"
      },
      {
        "evidence_id": "news.impact_score",
        "priority": 3,
        "use": "SUPPORT"
      }
    ],
    "support": "MEDIUM"
  },
  {
    "action": "PRESENT_CASE",
    "agent": "bear",
    "conflict": false,
    "direction": "BULLISH",
    "explanation_status": "VALID_UNVERIFIED",
    "local_nonblocking_probes": [
      {
        "explanation": "REJECTED",
        "kind": "number",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "OMITTED",
        "kind": "empty",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      }
    ],
    "selected": [
      {
        "evidence_id": "kronos.direction",
        "priority": 1,
        "use": "COUNTER"
      },
      {
        "evidence_id": "news.event.0",
        "priority": 2,
        "use": "COUNTER"
      },
      {
        "evidence_id": "technicals.indicator.11",
        "priority": 3,
        "use": "COUNTER"
      }
    ],
    "support": "INSUFFICIENT"
  },
  {
    "action": "FLAG_RISK",
    "agent": "risk",
    "conflict": false,
    "direction": "BULLISH",
    "explanation_status": "VALID_UNVERIFIED",
    "local_nonblocking_probes": [
      {
        "explanation": "REJECTED",
        "kind": "number",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "OMITTED",
        "kind": "empty",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      },
      {
        "explanation": "REJECTED",
        "kind": "unsafe_or_malformed",
        "structured": "PASS",
        "truth_unchanged": true
      }
    ],
    "selected": [
      {
        "evidence_id": "kronos.direction",
        "priority": 1,
        "use": "RISK"
      },
      {
        "evidence_id": "kronos.forecast_pct_change",
        "priority": 2,
        "use": "RISK"
      },
      {
        "evidence_id": "market_data.quality",
        "priority": 3,
        "use": "RISK"
      },
      {
        "evidence_id": "news.impact_score",
        "priority": 4,
        "use": "RISK"
      }
    ],
    "support": "MEDIUM"
  }
]
Actual provider explanation statuses are retained above. Bad/empty/unsafe prose probes use local copies of accepted live selections; they are not extra provider calls or fabricated live rejection examples.
No hidden reasoning, raw provider internals, credentials or environment values were persisted.
