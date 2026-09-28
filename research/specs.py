"""Scientific experiment identity separate from execution/run identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .config import BENCHMARK_PROFILE_VERSION, METRICS_VERSION, PREPROCESSING_VERSION, REGIME_VERSION
from .datasets import DatasetManifest
from .windows import BenchmarkWindow


@dataclass(frozen=True)
class ExperimentSpec:
    scientific_experiment_id: str
    forecast_identity_id: str
    analysis_identity_id: str
    dataset_id: str
    dataset_hash: str
    canonical_instrument_id: str | None
    symbol: str
    exchange: str
    cutoff: str
    context_start: str
    context_end: str
    future_start: str
    future_end: str
    lookback: int
    horizon: int
    stride: int
    interval: str
    session_policy: str
    model_id: str
    model_version: str
    tokenizer_id: str
    tokenizer_version: str
    temperature: float
    top_k: int
    top_p: float
    sample_count: int
    seed: int
    preprocessing_version: str
    metric_definition_version: str
    regime_definition_version: str
    benchmark_profile_version: str
    system_configuration_id: str
    purpose: str
    code_commit: str
    code_dirty_state: bool | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _hash(payload: dict[str, Any], prefix: str) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def build_experiment_spec(
    *,
    manifest: DatasetManifest,
    window: BenchmarkWindow,
    model_name: str,
    settings: dict[str, Any],
    system_configuration_id: str,
    purpose: str,
    model_provenance: dict[str, object],
    git: dict[str, object],
    seed: int,
) -> ExperimentSpec:
    forecast_identity = {
        "dataset_hash": manifest.dataset_hash_full,
        "symbol": manifest.symbol,
        "exchange": manifest.exchange,
        "cutoff": window.cutoff_timestamp,
        "context_start": window.context_start,
        "context_end": window.context_end,
        "future_start": window.future_start,
        "future_end": window.future_end,
        "lookback": window.lookback_bars,
        "horizon": window.horizon_bars,
        "interval": manifest.interval,
        "session_policy": window.session_policy,
        "model_id": model_provenance.get("model_id", model_name),
        "tokenizer_id": model_provenance.get("tokenizer_id", "unknown"),
        "sampling": settings,
        "seed": seed,
        "preprocessing_version": PREPROCESSING_VERSION,
        "system_configuration_id": system_configuration_id,
    }
    analysis_identity = {
        **forecast_identity,
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
        "benchmark_profile_version": BENCHMARK_PROFILE_VERSION,
    }
    forecast_id = _hash(forecast_identity, "forecast")
    analysis_id = _hash(analysis_identity, "analysis")
    experiment_id = _hash({"forecast_id": forecast_id, "analysis_id": analysis_id}, "exp")
    return ExperimentSpec(
        scientific_experiment_id=experiment_id,
        forecast_identity_id=forecast_id,
        analysis_identity_id=analysis_id,
        dataset_id=manifest.dataset_id,
        dataset_hash=manifest.dataset_hash_full,
        canonical_instrument_id=manifest.canonical_instrument_id,
        symbol=manifest.symbol,
        exchange=manifest.exchange,
        cutoff=window.cutoff_timestamp,
        context_start=window.context_start,
        context_end=window.context_end,
        future_start=window.future_start,
        future_end=window.future_end,
        lookback=window.lookback_bars,
        horizon=window.horizon_bars,
        stride=window.stride_bars,
        interval=manifest.interval,
        session_policy=window.session_policy,
        model_id=str(model_provenance.get("model_id", model_name)),
        model_version=str(model_provenance.get("model_version", model_name)),
        tokenizer_id=str(model_provenance.get("tokenizer_id", "unknown")),
        tokenizer_version=str(model_provenance.get("tokenizer_version", "unknown")),
        temperature=float(settings.get("temperature", 1.0)),
        top_k=int(settings.get("top_k", 0)),
        top_p=float(settings.get("top_p", 0.9)),
        sample_count=int(settings.get("sample_count", 1)),
        seed=seed,
        preprocessing_version=PREPROCESSING_VERSION,
        metric_definition_version=METRICS_VERSION,
        regime_definition_version=REGIME_VERSION,
        benchmark_profile_version=BENCHMARK_PROFILE_VERSION,
        system_configuration_id=system_configuration_id,
        purpose=purpose,
        code_commit=str(git.get("commit", "unknown")),
        code_dirty_state=git.get("dirty") if isinstance(git.get("dirty"), bool) else None,
    )
