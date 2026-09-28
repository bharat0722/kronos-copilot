# Benchmark Runbook

Run commands from the project folder.

## Dry Run

`python -m research.cli run --profile dry-run --dry-run`

Plans experiments without executing forecasts.

## Smoke

`python -m research.cli run --profile smoke`

Runs a tiny synthetic benchmark with fake adapter plus persistence, drift, and momentum.

## Small Real Kronos Smoke

`python -m research.cli run --profile dry-run --adapter kronos --run-id kronos_real_smoke`

This runs one synthetic 24-bar window through the real Kronos adapter. Use only when the machine is ready for local model inference.

## Quick

`python -m research.cli run --profile quick`

Runs a slightly larger synthetic engineering check across 24 and 75 bars.

## Standard

`python -m research.cli run --profile standard --dry-run`

Defined for real-market research planning. Do not launch without curated historical datasets.

## Full

`python -m research.cli run --profile full --dry-run`

Planning profile only until a curated historical dataset library is registered.

## Resume

Use:

`python -m research.cli resume RUN_ID`

Successful scientific experiments are reused. Failed experiments are not retried unless `--retry-failed` is supplied. Use `--force` only when intentionally creating another execution for the same scientific experiment.

If Ctrl+C interrupts a run, the runner marks the current experiment and run as interrupted, flushes concise logs, closes the registry, and prints a resume command.

## Report

`python -m research.cli report --run-id RUN_ID`

## Status

`python -m research.cli status --run-id RUN_ID`

## List And Inspect

`python -m research.cli list-runs`

`python -m research.cli inspect EXPERIMENT_ID`

## Locked Test Mechanics

`locked_test` is a protected profile shell for later real datasets. Phase 1A.2 implements the mechanics but does not register or download a real locked NSE/BSE dataset.

## Report Artifacts

Each run writes `run_manifest.json`, compressed path artifacts, logs, `summary.json`, `summary.md`, failure index, success index, and artifact index under `research/results/runs/<run_id>/`.

## Research UI

Open `research/research_lab.html` for the command-oriented Phase 1 lab landing page.
