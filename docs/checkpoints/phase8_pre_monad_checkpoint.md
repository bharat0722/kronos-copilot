# Kronos Copilot - Phase 8 Pre-Monad Checkpoint

## Purpose

This checkpoint captures the canonical Kronos Copilot main-project state immediately before a separate Monad / Metropolis hackathon workstream begins. It preserves the completed Phase 7 and Phase 8 implementation, contracts, tests, and final reports so the main roadmap can resume without repeating validated work.

The hackathon adaptation is a separate workstream. It must not redefine the scientific meaning, provenance, or completion status of the canonical main project.

## Current Status

| Milestone | Status |
|---|---|
| Phase 7 - Controlled Agent Architecture | COMPLETE |
| Phase 7.3B | PASS |
| Audit #4 - Agentic Architecture Quality Gate | PASS |
| Phase 8 - Evidence Fusion Engine | COMPLETE / PASS |
| Evidence Fusion version | `evidence_fusion_v1` |
| Phase 9 permission | YES |
| Locked test | UNTOUCHED |

Phase 7 is closed. It should not be reopened unless a genuine regression or architectural defect is discovered.

## What The System Currently Does

```text
Market Data
    |
    v
Bronze -> Silver -> Gold
    |
    +-> Kronos Forecast
    +-> Technical Intelligence
    +-> Market Regime
    +-> News / Events
    +-> Bull / Bear / Risk interpretation
              |
              v
       Evidence Fusion
              |
              v
   Explainable Research View
              |
              v
          Dashboard
```

Kronos Copilot is an evidence-first research and decision-support prototype. It does not provide investment advice, guaranteed predictions, or autonomous trading.

## Phase 7 Summary

Phase 7 provides:

- Bull, Bear, and Risk specialist agents;
- a deterministic orchestrator / aggregator;
- a bounded harness with no tools, a maximum loop count of 1, and one retry per failed agent;
- the shared `agent_output_v2` typed claim and support contract;
- explicit fact-versus-interpretation semantics;
- numerical and qualitative grounding;
- evidence lineage, claim traceability, and reference validation;
- prompt-injection protection and evidence immutability;
- version-safe cache behavior and a durable ledger;
- privacy, failure-handling, and bounded live-validation evidence.

The Phase 7.3A audit identified a qualitative grounding and traceability gap. Phase 7.3B closed that gap through the typed contract and offline validation, and records the final Audit #4 result as PASS.

## Phase 8 Summary

Phase 8 implements deterministic, traceable evidence fusion under version `evidence_fusion_v1`.

Available evidence sources are:

- Kronos forecast;
- technical intelligence;
- market regime;
- news and events;
- news impact;
- pipeline quality;
- valid cached Bull, Bear, and Risk outputs.

Fundamentals are not implemented and remain explicitly missing.

The fusion engine provides:

- a canonical evidence representation;
- primary-versus-derived evidence classification;
- direction normalization and bounded evidence strength;
- freshness and quality handling;
- explicit missing-evidence handling, where missing is not neutral;
- agreement and conflict detection;
- lineage-aware deduplication and double-counting protection;
- risk adjustment without automatically reversing direction;
- abstention when evidence is insufficient;
- a structured final research view with deterministic explanations;
- complete provenance, a versioned cache, a durable fusion ledger, and input immutability;
- dashboard integration and pipeline observability.

## Test Status

Latest known validated result:

- 184 passed
- 0 failed
- 1 skipped

The skipped test is the existing opt-in live Yahoo regression.

Tests rerun during checkpoint creation: **0**. The checkpoint task performed only repository, documentation, JSON, and Git integrity checks. It did not rerun product or research tests.

## Known Limitations

1. Fusion weights and thresholds are transparent but not historically calibrated.
2. No claim has been made that Evidence Fusion improves forecasting accuracy.
3. Fundamentals are not implemented.
4. Agent evidence is used only when valid cached Phase 7 outputs are available.
5. Support labels are qualitative support levels, not statistical probabilities.
6. Evidence Fusion has been functionally validated, but its incremental historical value has not yet been scientifically measured.

These limitations are the starting conditions for Phase 9. They are not reasons to reopen Phase 8.

## Waiting Model Track

The separate model and fine-tuning track remains paused at Phase 1E-C.2 because it requires provenance-clean historical Indian intraday data and stronger CUDA GPU / MU hardware support.

The intended sequence after those dependencies are resolved is:

```text
Phase 1E-C.2 - Real training data resolution
    -> Phase 1E-D - Kronos-small pilot fine-tune
    -> Phase 1E-E - Controlled India/NSE fine-tuning
    -> Phase 1E-F - Freeze India-Kronos winner
    -> Phase 1E-G - Fine-tuned validation
```

This waiting model track is separate from Phase 9.

## Next Main Phase

The next canonical main-project phase is **Phase 9 - Historical Evaluation**.

Its primary question is whether the complete Kronos Copilot intelligence stack, especially `evidence_fusion_v1`, adds measurable historical value over simpler systems such as persistence, drift, momentum, optimized Phase 1D Kronos, and progressively richer deterministic evidence combinations.

`evidence_fusion_v1` should remain frozen for the initial Phase 9 evaluation. Phase 9 evaluates it; it does not silently tune it during evaluation.

## Scientific Safety

- The locked test remains untouched and reserved for the later canonical final-test phase.
- Do not tune against locked-test data or inspect locked-test targets during the separate hackathon workstream or Phase 9 development evaluation.
- Preserve completed Phase 1, Phase 3, Phase 7, and Phase 8 results and their provenance.
- Do not rewrite historical experiment IDs, metrics, dataset hashes, validation membership, or artifact meaning.
- Preserve the final Phase 7 and Phase 8 reports and machine-readable contracts included with this checkpoint.

## Canonical Checkpoint Artifacts

The checkpoint includes the final Phase 7.3A/7.3B reports, selected Phase 7 closure contracts and risk register, the final Phase 8 report, and the complete `research/results/evidence_fusion/` contract set. Runtime ledgers, provider caches, local market data, environments, credentials, and other generated research output remain excluded from version control.

## Post-Hackathon Return Instruction

When the separate Monad / Metropolis workstream is concluded or paused, resume the canonical Kronos Copilot roadmap from Phase 9 - Historical Evaluation.

Do not repeat Phase 7 or Phase 8 unless a verified regression requires it. Start by reading this checkpoint, verifying the tagged source state, and preserving `evidence_fusion_v1` for the initial historical evaluation.
