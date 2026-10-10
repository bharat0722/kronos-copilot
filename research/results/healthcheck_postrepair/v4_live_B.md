# V4 Live Test B

Status: PASS
Fixture: synthetic_adversarial_v1_TESTCO
Snapshot: 6053e5ed66a87158392db3cf18fc94b13434c47c640e335eb71137d36e233edf
Serialized bytes: 19764
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
| bull | 1 | FAILED | - | 6233 | 170 | 6403 | completed | Agent evidence selection failed |
| bull | 2 | SUCCESS | VALID_UNVERIFIED | 6233 | 167 | 6400 | completed | - |
| bear | 1 | SUCCESS | VALID_UNVERIFIED | 6233 | 189 | 6422 | completed | - |
| risk | 1 | SUCCESS | VALID_UNVERIFIED | 6235 | 206 | 6441 | completed | - |

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
        "evidence_id": "news.event.0",
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
    "conflict": true,
    "direction": "MIXED",
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
        "evidence_id": "technicals.trend",
        "priority": 1,
        "use": "SUPPORT"
      },
      {
        "evidence_id": "technicals.indicator.0",
        "priority": 2,
        "use": "SUPPORT"
      },
      {
        "evidence_id": "kronos.direction",
        "priority": 3,
        "use": "COUNTER"
      }
    ],
    "support": "LOW"
  },
  {
    "action": "FLAG_RISK",
    "agent": "risk",
    "conflict": true,
    "direction": "MIXED",
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
        "evidence_id": "context.directional_conflict",
        "priority": 1,
        "use": "RISK"
      },
      {
        "evidence_id": "news.uncertainty",
        "priority": 2,
        "use": "RISK"
      },
      {
        "evidence_id": "technicals.regime",
        "priority": 3,
        "use": "RISK"
      },
      {
        "evidence_id": "kronos.direction",
        "priority": 4,
        "use": "RISK"
      }
    ],
    "support": "LOW"
  }
]
Actual provider explanation statuses are retained above. Bad/empty/unsafe prose probes use local copies of accepted live selections; they are not extra provider calls or fabricated live rejection examples.
No hidden reasoning, raw provider internals, credentials or environment values were persisted.
