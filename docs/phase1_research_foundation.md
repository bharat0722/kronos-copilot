# Phase 1 Research Foundation

Phase 1 answers one question: how good is the forecasting system we already have?

The live dashboard remains the product mode. The research lab is a separate benchmark mode that evaluates historical walk-forward windows against Kronos and simple baselines.

## Architecture

Human or benchmark profile -> dataset manifest -> walk-forward windows -> context bars visible at cutoff -> Kronos or baseline forecast -> hidden future -> metric engine -> regime tags -> SQLite registry -> markdown report.

## Methodology

Each experiment splits a chronological dataset into a context window and a hidden future window. Kronos and all baselines receive only context data. The hidden future is revealed only to the metric engine.

The default research profile uses a stride close to horizon length to reduce overlap. Dense overlapping profiles are allowed but must be reported as correlated observations.

## Baselines

- Persistence: every future close equals the last observed close.
- Drift: recent average close change from context is projected forward.
- Momentum: short moving average minus long moving average creates a simple deterministic slope.

These are intentionally simple. Kronos must beat them to show value.

## Storage And Resume

Experiments are stored in `research/results/experiments.sqlite3`. Completed successful experiments are not rerun when the same dataset, window, model, settings, metrics version, and regime version are requested again.

## Phase 1A.2 Scientific Hardening

Phase 1A.2 separates execution identity from scientific identity. A run ID answers when an execution happened. A scientific experiment ID answers what exact benchmark question was asked. The scientific ID is derived from dataset content hash, instrument identity, cutoff/window bounds, horizon, interval, session policy, model/tokenizer identity, sampling settings, seed, preprocessing version, and system configuration. It does not include the run ID.

Forecast identity and analysis identity are also separated. Forecast identity protects expensive model reuse. Analysis identity includes metric/regime/profile versions so analysis can be recomputed without pretending the model forecast changed.

Every dataset manifest now stores full SHA-256 content identity, acquisition and registration timestamps, source/provenance fields, quality status, quality report identity, session-policy capabilities, schema version, manifest version, and lineage placeholders for future raw/curated datasets.

Every executed experiment stores compressed CSV artifacts for prediction, actual hidden future, and a small context tail under `research/results/runs/<run_id>/artifacts/`. Registered immutable datasets plus window bounds remain the canonical source for reconstructing full context.

Runs record environment, Git state, model/tokenizer provenance, preprocessing version, and best-effort random seeds. PyTorch/CUDA determinism is documented as best effort unless the backend can guarantee stricter behavior.

## Limitations

The included smoke dataset is synthetic and validates engineering only. It must not be interpreted as real market performance. Large real benchmarks require curated historical data beyond what recent yfinance intraday data can always provide. Phase 1A.2 reports session/calendar gaps but does not infer every exchange holiday.
