"""Benchmark experiment planner and runner."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pandas as pd

from .adapters.kronos_adapter import FakeForecastAdapter, KronosForecastAdapter
from .baselines import BASELINES
from .config import BenchmarkProfile, METRICS_VERSION, REGIME_VERSION, ensure_research_dirs
from .datasets import DatasetManifest, synthetic_market_data
from .metrics import close_metrics
from .regimes import tag_regime
from .registry import ExperimentRegistry
from .reporting import generate_markdown_report
from .windows import BenchmarkWindow, generate_windows, split_window


def git_info() -> dict[str, object]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--short"], text=True).strip())
        branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
        return {"commit": commit, "dirty": dirty, "branch": branch}
    except Exception:
        return {"commit": "unknown", "dirty": None, "branch": "unknown"}


def experiment_id(*, run_id: str, dataset_id: str, window: BenchmarkWindow, model_name: str, settings: dict[str, Any], system_configuration_id: str) -> str:
    identity = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "window": asdict(window),
        "model_name": model_name,
        "settings": settings,
        "system_configuration_id": system_configuration_id,
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def run_model_experiment(
    *,
    registry: ExperimentRegistry,
    run_id: str,
    model_name: str,
    adapter: object,
    bars: pd.DataFrame,
    manifest: DatasetManifest,
    window: BenchmarkWindow,
    settings: dict[str, Any],
    system_configuration_id: str,
) -> bool:
    exp_id = experiment_id(run_id=run_id, dataset_id=manifest.dataset_id, window=window, model_name=model_name, settings=settings, system_configuration_id=system_configuration_id)
    payload = {
        "run_id": run_id,
        "system_configuration_id": system_configuration_id,
        "dataset_id": manifest.dataset_id,
        "symbol": manifest.symbol,
        "horizon_bars": window.horizon_bars,
        "model_name": model_name,
        "window": window,
        "settings": settings,
    }
    if not registry.start_experiment(exp_id, payload):
        return False
    try:
        context, future = split_window(bars, window)
        prediction, inference_seconds = adapter.predict(context, future, horizon_bars=window.horizon_bars, settings=settings)
        metrics = close_metrics(prediction, future, context)
        metrics["inference_seconds"] = inference_seconds
        if getattr(adapter, "model_load_seconds", None) is not None:
            metrics["model_load_seconds"] = getattr(adapter, "model_load_seconds")
        registry.finish_experiment(exp_id, metrics, tag_regime(context))
        return True
    except Exception as error:
        registry.fail_experiment(exp_id, str(error))
        return False


class BaselineAdapter:
    def __init__(self, name: str, fn):
        self.model_name = name
        self.fn = fn

    def predict(self, context: pd.DataFrame, future: pd.DataFrame, *, horizon_bars: int, settings: dict[str, object]) -> tuple[pd.DataFrame, float]:
        started = time.perf_counter()
        prediction = self.fn(context, future["timestamp"].reset_index(drop=True))
        return prediction, time.perf_counter() - started


def run_profile(profile: BenchmarkProfile, *, adapter_name: str = "fake", run_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    ensure_research_dirs()
    run_id = run_id or f"{profile.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    bars, manifest = synthetic_market_data(symbol=profile.symbols[0] if profile.symbols else "SYNTH")
    registry = ExperimentRegistry()
    run_manifest = {
        "run_id": run_id,
        "profile": asdict(profile),
        "dataset": manifest.as_dict(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git": git_info(),
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "adapter": adapter_name,
    }
    registry.record_run(run_id, run_manifest)
    planned = []
    settings = asdict(profile.sampling)
    for horizon in profile.horizons:
        windows = generate_windows(
            bars,
            symbol=manifest.symbol,
            lookback_bars=profile.lookback_bars,
            horizon_bars=horizon,
            stride_bars=profile.stride_bars,
            session_policy=profile.session_policy,
            max_windows=profile.max_windows_per_symbol,
        )
        planned.extend(windows)
    if dry_run:
        registry.finish_run(run_id, "dry-run")
        registry.close()
        return {"run_id": run_id, "planned_experiments": len(planned) * 4, "report_path": None}

    adapter = KronosForecastAdapter() if adapter_name == "kronos" else FakeForecastAdapter()
    executed = 0
    for window in planned:
        for baseline_name, fn in BASELINES.items():
            executed += int(run_model_experiment(
                registry=registry,
                run_id=run_id,
                model_name=baseline_name,
                adapter=BaselineAdapter(baseline_name, fn),
                bars=bars,
                manifest=manifest,
                window=window,
                settings=settings,
                system_configuration_id=profile.system_configuration_id,
            ))
        executed += int(run_model_experiment(
            registry=registry,
            run_id=run_id,
            model_name="kronos" if adapter_name == "kronos" else adapter.model_name,
            adapter=adapter,
            bars=bars,
            manifest=manifest,
            window=window,
            settings=settings,
            system_configuration_id=profile.system_configuration_id,
        ))
    registry.finish_run(run_id, "complete")
    report_path = generate_markdown_report(run_id, registry)
    summary = registry.summary(run_id)
    registry.close()
    return {
        "run_id": run_id,
        "planned_windows": len(planned),
        "executed_or_reused": executed,
        "summary": summary,
        "report_path": str(report_path),
    }


# Phase 1A.2 active runner overlay. The original functions above remain for
# reference, but this definition is the active import target.
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

from .artifacts import write_frame_artifact, write_json_artifact  # noqa: E402
from .datasets import quality_report  # noqa: E402
from .locks import ForecastLock  # noqa: E402
from .provenance import apply_seed, environment_info, git_info, model_provenance, stable_seed  # noqa: E402
from .specs import build_experiment_spec  # noqa: E402
from .stats import overlap_summary  # noqa: E402


class ControlledInterrupt(Exception):
    """Injected in tests to verify safe resume without manual Ctrl+C."""


def _append_run_log(run_id: str, event: str, message: str, *, level: str = "INFO", experiment_id: str | None = None) -> None:
    import json as _json

    directory = Path("research") / "results" / "runs" / run_id / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "run.jsonl"
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "event": event,
        "message": message,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_json.dumps(payload, sort_keys=True) + "\n")


def _adapter_for(adapter_name: str, model_name: str | None = None, fn=None):
    if fn is not None:
        return BaselineAdapter(model_name or "baseline", fn)
    return KronosForecastAdapter() if adapter_name == "kronos" else FakeForecastAdapter()


def _model_identity(model_name: str, adapter_name: str, settings: dict[str, Any] | None = None) -> dict[str, object]:
    if model_name == "kronos":
        identity = model_provenance()
        settings = settings or {}
        model_checkpoint = settings.get("model_checkpoint")
        tokenizer_checkpoint = settings.get("tokenizer_checkpoint")
        if model_checkpoint:
            identity = {**identity, "model_id": model_checkpoint, "model_variant": str(model_checkpoint).rsplit("/", 1)[-1]}
        if tokenizer_checkpoint:
            identity = {**identity, "tokenizer_id": tokenizer_checkpoint}
        return identity
    return {
        "model_family": "baseline" if model_name in BASELINES else "test",
        "model_variant": model_name,
        "model_id": model_name,
        "model_version": "phase1a2_baseline_v1",
        "tokenizer_id": "none",
        "tokenizer_version": "none",
    }


def run_model_experiment(
    *,
    registry: ExperimentRegistry,
    run_id: str,
    model_name: str,
    adapter: object,
    bars: pd.DataFrame,
    manifest: DatasetManifest,
    window: BenchmarkWindow,
    settings: dict[str, Any],
    system_configuration_id: str,
    purpose: str = "smoke",
    force: bool = False,
    retry_failed: bool = False,
    adapter_name: str = "fake",
) -> bool:
    git = git_info()
    identity = _model_identity(model_name, adapter_name, settings)
    seed = stable_seed({
        "dataset_hash": manifest.dataset_hash_full,
        "window": asdict(window),
        "model": identity,
        "settings": settings,
        "system_configuration_id": system_configuration_id,
    })
    spec = build_experiment_spec(
        manifest=manifest,
        window=window,
        model_name=model_name,
        settings=settings,
        system_configuration_id=system_configuration_id,
        purpose=purpose,
        model_provenance=identity,
        git=git,
        seed=seed,
    )
    exp_id = spec.scientific_experiment_id
    existing = registry.get_status(exp_id)
    if existing == "failed" and not retry_failed and not force:
        registry.log(run_id, exp_id, "INFO", "skipped_failed", "Failed experiment not retried without --retry-failed.")
        registry.connection.commit()
        return False
    registry.record_spec(spec)
    payload = {
        "run_id": run_id,
        "system_configuration_id": system_configuration_id,
        "dataset_id": manifest.dataset_id,
        "symbol": manifest.symbol,
        "horizon_bars": window.horizon_bars,
        "model_name": model_name,
        "window": window,
        "settings": settings,
    }
    if not registry.start_experiment(exp_id, payload, force=force):
        return False
    _append_run_log(run_id, "experiment_started", f"{model_name} horizon {window.horizon_bars}", experiment_id=exp_id)
    try:
        apply_seed(seed)
        context, future = split_window(bars, window)
        if model_name == "kronos":
            with ForecastLock(f"benchmark:{run_id}:{exp_id}", timeout_seconds=float(settings.get("lock_timeout_seconds", 1800))):
                prediction, inference_seconds = adapter.predict(context, future, horizon_bars=window.horizon_bars, settings=settings)
        else:
            prediction, inference_seconds = adapter.predict(context, future, horizon_bars=window.horizon_bars, settings=settings)
        metrics = close_metrics(prediction, future, context)
        metrics["inference_seconds"] = inference_seconds
        metrics["seed"] = seed
        metrics.update(apply_seed(seed))
        if getattr(adapter, "model_load_seconds", None) is not None:
            metrics["model_load_seconds"] = getattr(adapter, "model_load_seconds")
        artifacts = [
            write_frame_artifact(run_id, exp_id, "prediction", prediction),
            write_frame_artifact(run_id, exp_id, "actual", future),
            write_frame_artifact(run_id, exp_id, "context_tail", context.tail(80)),
        ]
        registry.finish_experiment(exp_id, metrics, tag_regime(context), run_id=run_id, artifacts=artifacts)
        _append_run_log(run_id, "experiment_succeeded", model_name, experiment_id=exp_id)
        return True
    except KeyboardInterrupt:
        registry.interrupt_experiment(exp_id, run_id)
        _append_run_log(run_id, "experiment_interrupted", "Benchmark interrupted safely.", level="WARNING", experiment_id=exp_id)
        raise
    except ControlledInterrupt:
        registry.interrupt_experiment(exp_id, run_id)
        _append_run_log(run_id, "experiment_interrupted", "Controlled interruption for resume testing.", level="WARNING", experiment_id=exp_id)
        raise
    except Exception as error:
        trace_path = Path("research") / "results" / "runs" / run_id / "logs" / f"{exp_id}_traceback.txt"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(traceback.format_exc(), encoding="utf-8")
        registry.fail_experiment(exp_id, str(error), run_id=run_id, error_type=type(error).__name__)
        _append_run_log(run_id, "experiment_failed", str(error), level="ERROR", experiment_id=exp_id)
        return False


def _planned_windows(profile: BenchmarkProfile, bars: pd.DataFrame, manifest: DatasetManifest) -> list[BenchmarkWindow]:
    planned: list[BenchmarkWindow] = []
    for horizon in profile.horizons:
        planned.extend(generate_windows(
            bars,
            symbol=manifest.symbol,
            lookback_bars=profile.lookback_bars,
            horizon_bars=horizon,
            stride_bars=profile.stride_bars,
            session_policy=profile.session_policy,
            max_windows=profile.max_windows_per_symbol,
        ))
    return planned


def run_profile(
    profile: BenchmarkProfile,
    *,
    adapter_name: str = "fake",
    run_id: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    retry_failed: bool = False,
    interrupt_after: int | None = None,
) -> dict[str, Any]:
    ensure_research_dirs()
    run_id = run_id or f"{profile.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    bars, manifest = synthetic_market_data(symbol=profile.symbols[0] if profile.symbols else "SYNTH")
    quality = quality_report(bars)
    registry = ExperimentRegistry()
    registry.register_dataset(manifest, quality)
    planned = _planned_windows(profile, bars, manifest)
    settings = asdict(profile.sampling)
    model_names = [*BASELINES.keys(), "kronos" if adapter_name == "kronos" else FakeForecastAdapter.model_name]
    run_manifest = {
        "run_id": run_id,
        "profile": asdict(profile),
        "dataset": manifest.as_dict(),
        "quality": quality.as_dict(),
        "environment": environment_info(),
        "model_provenance": model_provenance(),
        "git": git_info(),
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
        "preprocessing_version": "phase1-preprocessing-v1",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "adapter": adapter_name,
        "planned_windows": len(planned),
        "planned_experiments": len(planned) * len(model_names),
        "overlap": [overlap_summary(horizon, profile.stride_bars) for horizon in profile.horizons],
        "purpose": profile.name,
    }
    registry.record_run(run_id, run_manifest, "planning" if dry_run else "running")
    write_json_artifact(run_id, "run_manifest.json", run_manifest)
    if dry_run:
        registry.finish_run(run_id, "dry_run")
        registry.close()
        return {
            "run_id": run_id,
            "planned_windows": len(planned),
            "planned_experiments": len(planned) * len(model_names),
            "estimated_kronos_calls": len(planned) if adapter_name == "kronos" else 0,
            "estimated_storage_files": len(planned) * len(model_names) * 3,
            "report_path": None,
        }

    executed = 0
    attempted = 0
    adapter = KronosForecastAdapter() if adapter_name == "kronos" else FakeForecastAdapter()
    try:
        for window in planned:
            for baseline_name, fn in BASELINES.items():
                attempted += 1
                if interrupt_after is not None and attempted > interrupt_after:
                    raise ControlledInterrupt("Controlled benchmark interruption.")
                executed += int(run_model_experiment(
                    registry=registry,
                    run_id=run_id,
                    model_name=baseline_name,
                    adapter=BaselineAdapter(baseline_name, fn),
                    bars=bars,
                    manifest=manifest,
                    window=window,
                    settings=settings,
                    system_configuration_id=profile.system_configuration_id,
                    purpose=profile.name,
                    force=force,
                    retry_failed=retry_failed,
                    adapter_name=adapter_name,
                ))
            attempted += 1
            if interrupt_after is not None and attempted > interrupt_after:
                raise ControlledInterrupt("Controlled benchmark interruption.")
            executed += int(run_model_experiment(
                registry=registry,
                run_id=run_id,
                model_name="kronos" if adapter_name == "kronos" else adapter.model_name,
                adapter=adapter,
                bars=bars,
                manifest=manifest,
                window=window,
                settings=settings,
                system_configuration_id=profile.system_configuration_id,
                purpose=profile.name,
                force=force,
                retry_failed=retry_failed,
                adapter_name=adapter_name,
            ))
        status = "completed_with_errors" if registry.summary(run_id)["failed_count"] else "completed"
        registry.finish_run(run_id, status)
    except KeyboardInterrupt:
        registry.finish_run(run_id, "interrupted")
        registry.close()
        print(f"Benchmark interrupted safely.\nRun ID: {run_id}\nResume using: python -m research.cli resume {run_id}")
        raise SystemExit(130)
    except ControlledInterrupt:
        registry.finish_run(run_id, "interrupted")
        summary = registry.summary(run_id)
        registry.close()
        return {"run_id": run_id, "status": "interrupted", "summary": summary, "resume_command": f"python -m research.cli resume {run_id}"}
    report_path = generate_markdown_report(run_id, registry)
    summary = registry.summary(run_id)
    registry.close()
    return {
        "run_id": run_id,
        "planned_windows": len(planned),
        "executed_or_reused": executed,
        "summary": summary,
        "report_path": str(report_path),
    }


def resume_run(run_id: str, *, retry_failed: bool = False, force: bool = False) -> dict[str, Any]:
    registry = ExperimentRegistry()
    manifest = registry.get_run_manifest(run_id)
    registry.close()
    if not manifest:
        raise ValueError(f"Run ID was not found: {run_id}")
    from .profiles import get_profile

    profile = get_profile(manifest["profile"]["name"])
    return run_profile(profile, adapter_name=manifest.get("adapter", "fake"), run_id=run_id, force=force, retry_failed=retry_failed)
