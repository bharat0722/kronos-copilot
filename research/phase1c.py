"""Phase 1C canonical Kronos baseline benchmark orchestration."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .adapters.kronos_adapter import KronosForecastAdapter
from .baselines import BASELINES
from .config import (
    BENCHMARK_PROFILE_VERSION,
    DEFAULT_SYSTEM_CONFIGURATION_ID,
    METRICS_VERSION,
    PREPROCESSING_VERSION,
    REGIME_VERSION,
    REPORTS_DIR,
)
from .provenance import environment_info, git_info, model_provenance
from .real_market import SPLIT_PATH, _check_unlock, _read_json, load_dataset
from .registry import ExperimentRegistry
from .runner import BaselineAdapter, run_model_experiment
from .stats import bootstrap_ci, describe, paired_comparisons
from .windows import BenchmarkWindow


CANONICAL_KRONOS_BASE_V1 = {
    "configuration_id": "kronos_base_v1",
    "system_configuration_id": DEFAULT_SYSTEM_CONFIGURATION_ID,
    "model_name": "kronos",
    "lookback_bars": 400,
    "horizons": [24, 75, 120],
    "temperature": 1.0,
    "T": 1.0,
    "top_k": 0,
    "top_p": 0.9,
    "sample_count": 1,
    "seed_policy": "deterministic per dataset/window/model/settings",
    "checkpointing": "registry-backed scientific experiment IDs",
}


def canonical_settings() -> dict[str, object]:
    return {
        "temperature": CANONICAL_KRONOS_BASE_V1["temperature"],
        "top_k": CANONICAL_KRONOS_BASE_V1["top_k"],
        "top_p": CANONICAL_KRONOS_BASE_V1["top_p"],
        "sample_count": CANONICAL_KRONOS_BASE_V1["sample_count"],
    }


def _manifest_object(manifest_dict: dict[str, Any]) -> object:
    manifest = type("Manifest", (), {"as_dict": lambda self, data=manifest_dict: data})()
    for key, value in manifest_dict.items():
        setattr(manifest, key, value)
    return manifest


def _selected_windows(split: str, horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    _check_unlock(split, None)
    segmentation = _read_json(SPLIT_PATH)
    return [
        row for row in segmentation["windows"]
        if row["split"] == split and int(row["horizon"]) in horizons
    ]


def run_phase1c(
    *,
    split: str,
    model_set: str,
    run_id: str | None = None,
    horizons: tuple[int, ...] = (24, 75, 120),
    retry_failed: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if split == "locked_test":
        raise PermissionError("Phase 1C must not evaluate locked_test.")
    run_id = run_id or f"phase1c_{split}"
    windows = _selected_windows(split, horizons)
    registry = ExperimentRegistry()
    manifest = {
        "run_id": run_id,
        "phase": "1C",
        "split": split,
        "model_set": model_set,
        "canonical_config": CANONICAL_KRONOS_BASE_V1,
        "model_provenance": model_provenance(),
        "environment": environment_info(),
        "git": git_info(),
        "dataset_source": "frozen Phase 1B segmentation",
        "segmentation_path": str(SPLIT_PATH),
        "planned_windows": len(windows),
        "horizons": list(horizons),
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "benchmark_profile_version": BENCHMARK_PROFILE_VERSION,
    }
    registry.record_run(run_id, manifest, "running")
    settings = canonical_settings()
    executed = 0
    started = time.perf_counter()
    kronos_adapter = KronosForecastAdapter() if model_set in {"kronos", "all"} else None
    try:
        for row in windows:
            frame, manifest_dict, _, _ = load_dataset(row["symbol"])
            dataset_manifest = _manifest_object(manifest_dict)
            window = BenchmarkWindow(**row["window"])
            if model_set in {"baselines", "all"}:
                for baseline_name, fn in BASELINES.items():
                    executed += int(run_model_experiment(
                        registry=registry,
                        run_id=run_id,
                        model_name=baseline_name,
                        adapter=BaselineAdapter(baseline_name, fn),
                        bars=frame,
                        manifest=dataset_manifest,
                        window=window,
                        settings=settings,
                        system_configuration_id=DEFAULT_SYSTEM_CONFIGURATION_ID,
                        purpose=f"phase1c_{split}",
                        force=force,
                        retry_failed=retry_failed,
                        adapter_name="kronos",
                    ))
            if model_set in {"kronos", "all"}:
                executed += int(run_model_experiment(
                    registry=registry,
                    run_id=run_id,
                    model_name="kronos",
                    adapter=kronos_adapter,
                    bars=frame,
                    manifest=dataset_manifest,
                    window=window,
                    settings=settings,
                    system_configuration_id=DEFAULT_SYSTEM_CONFIGURATION_ID,
                    purpose=f"phase1c_{split}",
                    force=force,
                    retry_failed=retry_failed,
                    adapter_name="kronos",
                ))
        status = "completed_with_errors" if registry.summary(run_id)["failed_count"] else "completed"
        registry.finish_run(run_id, status)
    except KeyboardInterrupt:
        registry.finish_run(run_id, "interrupted")
        registry.close()
        raise
    summary = registry.summary(run_id)
    registry.close()
    return {
        "run_id": run_id,
        "split": split,
        "model_set": model_set,
        "planned_windows": len(windows),
        "executed_or_reused": executed,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "summary": summary,
    }


def _records(run_id: str) -> list[dict[str, Any]]:
    registry = ExperimentRegistry()
    try:
        return registry.metric_records(run_id)
    finally:
        registry.close()


def _grouped(records: list[dict[str, Any]], keys: tuple[str, ...], metric: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        parts = []
        for key in keys:
            if key == "regime":
                regime = record.get("regime") or {}
                parts.append(f"{regime.get('trend')}|{regime.get('volatility')}|{regime.get('open_close_zone')}")
            else:
                parts.append(str(record.get(key)))
        grouped[" / ".join(parts)].append(record)
    return {name: paired_comparisons(rows, metric) for name, rows in grouped.items()}


def _model_metric_summary(records: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        value = record.get(metric)
        if value is not None:
            grouped[str(record["model_name"])].append(float(value))
    return {model: describe(values) | {"ci": bootstrap_ci(values)} for model, values in grouped.items()}


def _worst_kronos(records: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    rows = [r for r in records if r.get("model_name") == "kronos" and r.get("normalized_mae") is not None]
    rows.sort(key=lambda r: float(r["normalized_mae"]), reverse=True)
    return [
        {
            "symbol": row["symbol"],
            "horizon": row["horizon_bars"],
            "cutoff": row.get("cutoff"),
            "normalized_mae": row.get("normalized_mae"),
            "mae": row.get("mae"),
            "directional_match": row.get("directional_match"),
            "regime": row.get("regime"),
        }
        for row in rows[:limit]
    ]


def phase1c_report(*, split: str, run_id: str | None = None) -> Path:
    run_id = run_id or f"phase1c_{split}"
    records = _records(run_id)
    registry = ExperimentRegistry()
    summary = registry.summary(run_id)
    manifest = registry.get_run_manifest(run_id)
    registry.close()
    metrics = [
        "mae", "normalized_mae", "rmse", "mape", "smape", "mase", "final_error",
        "final_error_pct", "total_return_error", "step_directional_match_pct",
        "correlation", "return_correlation", "range_error", "volatility_error",
        "open_mae", "high_mae", "low_mae", "close_mae", "ohlc_aggregate_error",
    ]
    payload = {
        "run_id": run_id,
        "split": split,
        "summary": summary,
        "canonical_config": CANONICAL_KRONOS_BASE_V1,
        "run_manifest": manifest,
        "model_metric_summary": {metric: _model_metric_summary(records, metric) for metric in metrics},
        "paired_by_metric": {metric: paired_comparisons(records, metric) for metric in metrics},
        "paired_by_horizon_mae": _grouped(records, ("horizon_bars",), "mae"),
        "paired_by_symbol_mae": _grouped(records, ("symbol",), "mae"),
        "paired_by_regime_mae": _grouped(records, ("regime",), "mae"),
        "worst_kronos_cases": _worst_kronos(records),
        "overlap_warnings": sorted({
            f"horizon {int(r['horizon_bars'])}: stride 120, overlap {max(0, int(r['horizon_bars']) - 120)} bars"
            for r in records
        }),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"phase1c_kronos_baseline_{split}.json"
    md_path = REPORTS_DIR / f"phase1c_kronos_baseline_{split}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [
        f"# Phase 1C Canonical Kronos Baseline Benchmark — {split.title()}",
        "",
        f"- Run ID: `{run_id}`",
        f"- Experiments: {summary.get('experiment_count', 0)}",
        f"- Success: {summary.get('success_count', 0)}",
        f"- Failed: {summary.get('failed_count', 0)}",
        f"- Skipped cached: {summary.get('skipped_cached_count', 0)}",
        f"- Canonical config: `kronos_base_v1`",
        f"- Locked test evaluated: `false`",
        "",
        "## Canonical Configuration",
        "```json",
        json.dumps(CANONICAL_KRONOS_BASE_V1 | {"model_provenance": model_provenance()}, indent=2, default=str),
        "```",
        "",
        "## Overall Kronos vs Baselines",
        "Negative delta means Kronos has lower error than the baseline.",
        "```json",
        json.dumps(payload["paired_by_metric"]["mae"], indent=2),
        "```",
        "",
        "## By Horizon",
        "```json",
        json.dumps(payload["paired_by_horizon_mae"], indent=2),
        "```",
        "",
        "## By Symbol",
        "```json",
        json.dumps(payload["paired_by_symbol_mae"], indent=2),
        "```",
        "",
        "## By Regime",
        "```json",
        json.dumps(payload["paired_by_regime_mae"], indent=2),
        "```",
        "",
        "## Metric Coverage",
        "```json",
        json.dumps(payload["model_metric_summary"], indent=2),
        "```",
        "",
        "## Worst Kronos Cases",
        "```json",
        json.dumps(payload["worst_kronos_cases"], indent=2, default=str),
        "```",
        "",
        "## Interpretation Guardrail",
        "Only groups with sample_status OK and non-null bootstrap intervals should be treated as statistically meaningful. Small-N groups are diagnostic only.",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
