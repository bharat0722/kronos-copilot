# Phase 8 - Evidence Fusion Engine

**Status:** PASS  
**Version:** `evidence_fusion_v1`  
**Mode:** Local, deterministic, offline-first  
**External calls:** 0

## Decision

Phase 8 is complete. Kronos Copilot now produces one structured research view from existing immutable evidence without asking another model to synthesize the answer. The engine preserves disagreements, reports absent sources explicitly, treats agent output as derived interpretation, and records complete lineage, cache identity, and a durable run ledger.

Phase 8 does **not** claim better forecast accuracy. The weights and thresholds are transparent conservative rules; Phase 9 must evaluate their historical value without tuning on locked-test data.

## Evidence Availability

| Source | Implemented | Structured | Freshness | Provenance | Quality | Phase 8 use |
|---|---:|---:|---:|---:|---:|---|
| Kronos forecast | Yes | Yes | Yes | Yes | Yes | Primary direction |
| Technical intelligence | Yes | Yes | Yes | Yes | Yes | Primary direction |
| News / events | Yes | Yes | Yes | Yes | Yes | Primary context |
| News impact | Yes | Yes | Yes | Yes | Yes | Direction only when qualifying |
| Market regime | Yes | Yes | Yes | Yes | Yes | Context; not counted twice |
| Pipeline health | Yes | Yes | Yes | Yes | Yes | Meta-evidence only |
| Bull / Bear / Risk agents | Yes | Yes | Yes | Yes | Yes | Cached interpretation only |
| Phase 6.2 preliminary view | Yes | Yes | Yes | Yes | Yes | Excluded from score to avoid recursive double counting |
| Fundamentals | No | No | No | No | No | Explicitly unavailable |

## Architecture

```text
EvidenceSnapshotV1 + cached agent_output_v2 + pipeline health
                         |
                         v
                 EvidenceItem normalization
                         |
                         v
               Quality / freshness gates
                         |
                         v
                Lineage deduplication
                         |
                         v
        Primary direction aggregation (rules only)
                         |
          +--------------+---------------+
          v                              v
   Agreement/conflict             Risk/support adjustment
          +--------------+---------------+
                         v
             Structured research view
                         |
              Cache + durable ledger
```

Only `FORECAST`, `TECHNICAL`, and qualifying `NEWS` items can affect direction. `REGIME` shares technical lineage and is context only. Bull, Bear, and Risk agent outputs preserve their claim evidence IDs but receive no independent directional vote. Pipeline health affects completeness/support, never market direction.

## Semantics

- **Direction:** strongly bearish, bearish, neutral/mixed, bullish, strongly bullish, or unknown.
- **Strength:** bounded rule-based support inside one source. It is not a probability or expected return.
- **Support:** low, medium, or high qualitative evidence agreement.
- **Quality:** good, limited, or poor based on upstream quality, freshness, and required source availability.
- **Missing:** no EvidenceItem is created. Missing evidence is never converted into neutral evidence.
- **Risk:** lowers support and exposes warnings; it does not automatically reverse direction.
- **Abstention:** `INSUFFICIENT_EVIDENCE` when fewer than two usable primary streams or no usable directional signal remains.

## Fusion Rules

V1 uses fixed, documented source weights: forecast `1.0`, technical trend `1.0`, and qualifying news impact `0.75`. `WARN` and `AGING` inputs are reduced; `FAIL` and `STALE` inputs are excluded. Strong views require aligned independent primary sources. Primary contradictions are preserved as conflict objects and normally lower support.

These numbers are algorithm settings, not calibrated probabilities. They were not tuned against validation or locked-test data.

## Double-Counting Protection

1. Agent claims retain references to the original evidence catalog.
2. Every agent output is marked `DERIVED` and contributes zero directional weight.
3. Regime is not counted independently from technical indicators.
4. Repeating a Kronos claim in Bull/Bear/Risk output cannot increase the Kronos contribution.
5. The prior Phase 6.2 research view is excluded from aggregation because it already derives from Kronos, technicals, and news.

## Product Integration

The authenticated read-only `/api/fusion` route consumes the current immutable snapshot, cached agent results, and local pipeline state. It cannot run agents, providers, Kronos, or network calls. The dashboard now shows:

- overall research view;
- support, evidence quality, and risk;
- deterministic explanation;
- supporting and opposing evidence;
- conflicts, risks, and missing sources;
- fusion run and snapshot lineage;
- Evidence Fusion pipeline health, latency, completeness, conflicts, and cache status.

No BUY/SELL language or execution capability was added.

## Verification

- **Offline regression:** 184 passed, 0 failed, 1 skipped.
- **Synthetic matrix:** all 15 required scenarios passed.
- **Saved snapshot smoke:** persisted `NSE:TCS` evidence produced `MIXED`, `LOW` support, and explicitly missing Bull/Bear/Risk outputs; no source/model call occurred.
- **Dashboard:** desktop, phone, and iPad widths passed with no horizontal overflow and no browser console errors.
- **Cache:** identical upstream evidence hits the same versioned cache identity; changed agent evidence invalidates it.
- **Ledger:** each fusion invocation records run ID, input IDs/hashes, version, output, conflicts, missing evidence, quality, latency, and cache state.
- **Immutability:** snapshot and agent inputs remain byte-identical before and after fusion.

The skipped test is the pre-existing opt-in live Yahoo regression. It was not enabled because this phase required offline execution.

## Safety

| Action | Count |
|---|---:|
| OpenAI calls | 0 |
| Other LLM calls | 0 |
| Tavily calls | 0 |
| Other external API calls | 0 |
| Kronos inference | 0 |
| Kronos training | 0 |
| Model-weight changes | 0 |
| Validation reruns | 0 |
| Locked-test target accesses | 0 |
| Trading actions | 0 |

## Known Limitations

- Fusion v1 has not been historically calibrated; Phase 9 must evaluate it.
- Fundamentals are unavailable.
- Agents contribute only when a valid cached Phase 7 result exists.
- Forecast freshness uses joined market/snapshot time because the snapshot lacks a separate forecast-generation timestamp.
- The engine does not include a historically calibrated reliability prior for Kronos in the snapshot contract.
- Support labels are qualitative and must not be displayed as a chance of price movement.

## Phase 9 Gate

**Permission:** YES.

Phase 9 may perform Historical Evaluation of `evidence_fusion_v1`, preserving frozen research results and locked-test isolation. It must test the rules rather than silently tune them on validation.
