"""Statistical summaries, paired comparisons, and deterministic bootstrap CIs."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean, median, pstdev
from typing import Any

from .config import BOOTSTRAP_CONFIDENCE, BOOTSTRAP_RESAMPLES, MINIMUM_RESEARCH_N


def describe(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and not math.isnan(float(value))]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "max": None, "sample_status": "INSUFFICIENT_SAMPLE"}
    return {
        "n": len(clean),
        "mean": mean(clean),
        "median": median(clean),
        "std": pstdev(clean) if len(clean) > 1 else 0.0,
        "min": min(clean),
        "max": max(clean),
        "sample_status": "OK" if len(clean) >= MINIMUM_RESEARCH_N else "INSUFFICIENT_SAMPLE",
    }


def bootstrap_ci(values: list[float], *, seed: int = 20260825, resamples: int = BOOTSTRAP_RESAMPLES, confidence: float = BOOTSTRAP_CONFIDENCE) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and not math.isnan(float(value))]
    if len(clean) < MINIMUM_RESEARCH_N:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(clean), "low": None, "high": None, "resamples": resamples}
    rng = random.Random(seed)
    estimates = []
    for _ in range(resamples):
        sample = [clean[rng.randrange(len(clean))] for _ in clean]
        estimates.append(mean(sample))
    estimates.sort()
    alpha = (1 - confidence) / 2
    low = estimates[int(alpha * (len(estimates) - 1))]
    high = estimates[int((1 - alpha) * (len(estimates) - 1))]
    return {"status": "OK", "n": len(clean), "low": low, "high": high, "resamples": resamples, "confidence": confidence}


def aggregate_metrics(records: list[dict[str, Any]], metric: str = "mae") -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        value = record.get(metric)
        if value is not None:
            grouped[str(record.get("model_name", "unknown"))].append(float(value))
    return {model: describe(values) for model, values in grouped.items()}


def paired_comparisons(records: list[dict[str, Any]], metric: str = "mae") -> dict[str, Any]:
    by_window: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        key = (str(record.get("symbol")), int(record.get("horizon_bars", 0)), str(record.get("cutoff", "")))
        by_window[key][str(record.get("model_name"))] = record
    results: dict[str, Any] = {}
    for baseline in ("persistence", "drift", "momentum"):
        deltas: list[float] = []
        wins = losses = ties = 0
        for models in by_window.values():
            if "kronos" not in models or baseline not in models:
                continue
            k = models["kronos"].get(metric)
            b = models[baseline].get(metric)
            if k is None or b is None:
                continue
            delta = float(k) - float(b)
            deltas.append(delta)
            if delta < 0:
                wins += 1
            elif delta > 0:
                losses += 1
            else:
                ties += 1
        n = len(deltas)
        results[baseline] = {
            "metric": metric,
            "n": n,
            "mean_delta": mean(deltas) if deltas else None,
            "median_delta": median(deltas) if deltas else None,
            "win_count": wins,
            "loss_count": losses,
            "tie_count": ties,
            "win_rate": wins / n * 100 if n else None,
            "ci": bootstrap_ci(deltas),
            "sample_status": "OK" if n >= MINIMUM_RESEARCH_N else "INSUFFICIENT_SAMPLE",
        }
    return results


def overlap_summary(horizon: int, stride: int) -> dict[str, Any]:
    overlap = max(0, horizon - stride)
    ratio = overlap / horizon if horizon else 0
    return {
        "horizon": horizon,
        "stride": stride,
        "overlap_bars": overlap,
        "overlap_ratio": ratio,
        "warning": ratio > 0.5,
    }
