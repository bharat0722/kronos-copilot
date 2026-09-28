# Temporal Integrity

Phase 1 uses this checklist for every benchmark:

- Context bars end at the cutoff.
- Hidden future starts after the cutoff.
- No future bars enter model input.
- Baselines use context only.
- Regime tags use context only.
- Metrics see future data only after prediction is produced.
- No future normalization is used.
- Horizons are market bars, not continuous wall-clock periods.
- Session policy is recorded.
- Stride is recorded because overlapping windows are correlated.
- Locked test sets should be separated before parameter tuning.

Automated tests verify cutoff indexing and fail if context reaches hidden future.

## Phase 1A.2 Hardening

Window records now store overlap bars and overlap ratio. Reports warn that overlapping windows are correlated.

Dataset validation emits structured quality issues with severity, code, count, and limited timestamp samples. It checks timestamp parsing, ordering, duplicates, OHLC NaNs, nonnumeric values, negative prices, negative volume, OHLC high/low integrity, zero-volume patterns, extreme discontinuities, missing bars inside a session, bars outside regular session time, and unknown calendar/session gaps.

Session gap reporting intentionally separates deterministic missing-session bars from unknown calendar gaps. It does not silently fill missing bars and does not assume a complete holiday calendar in Phase 1A.2.

Adversarial test coverage now verifies that context, baselines, regimes, and experiment specs remain pre-cutoff, and that future data affects scoring only.
