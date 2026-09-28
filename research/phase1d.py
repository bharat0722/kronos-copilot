"""Phase 1D optimized zero-shot Kronos research workflow."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd

from .adapters.kronos_adapter import KronosForecastAdapter
from .config import DEFAULT_SYSTEM_CONFIGURATION_ID, REPORTS_DIR, RESULTS_DIR, RUNS_DIR
from .phase1c import CANONICAL_KRONOS_BASE_V1, canonical_settings
from .real_market import SPLIT_PATH, _check_unlock, _read_json, load_dataset
from .registry import ExperimentRegistry
from .runner import run_model_experiment
from .stats import bootstrap_ci, describe
from .windows import BenchmarkWindow, split_window, validate_window_bounds


PHASE = "1D"
SEED = 20260828
BASELINES = ("persistence", "drift", "momentum")
PHASE1D_STATE_DIR = RESULTS_DIR / "phase1d"
PHASE1D_LOG_DIR = PHASE1D_STATE_DIR / "logs"
ROUND_RUN_IDS = {
    "round1": "phase1d_round1_v2",
    "round2": "phase1d_round2",
    "round3": "phase1d_round3",
    "validation": "phase1d_validation",
}
TUNING_SUBSET_JSON = REPORTS_DIR / "phase1d_tuning_subset.json"
TUNING_SUBSET_MD = REPORTS_DIR / "phase1d_tuning_subset.md"
CANDIDATES_JSON = REPORTS_DIR / "phase1d_candidates.json"
CANDIDATES_MD = REPORTS_DIR / "phase1d_candidates.md"
FAILURE_JSON = REPORTS_DIR / "phase1d_failure_diagnosis.json"
FAILURE_MD = REPORTS_DIR / "phase1d_failure_diagnosis.md"
AUDIT_JSON = REPORTS_DIR / "phase1d_inference_audit.json"
AUDIT_MD = REPORTS_DIR / "phase1d_inference_audit.md"


@dataclass(frozen=True)
class Candidate:
    config_id: str
    label: str
    settings: dict[str, Any]
    rationale: str


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _manifest_object(manifest_dict: dict[str, Any]) -> object:
    manifest = type("Manifest", (), {"as_dict": lambda self, data=manifest_dict: data})()
    for key, value in manifest_dict.items():
        setattr(manifest, key, value)
    return manifest


def _segmentation() -> dict[str, Any]:
    return _read_json(SPLIT_PATH)


def _selected_windows(split: str, horizons: tuple[int, ...] = (24, 75, 120)) -> list[dict[str, Any]]:
    _check_unlock(split, None)
    if split == "locked_test":
        raise PermissionError("Phase 1D must not read or evaluate locked_test.")
    return [
        row for row in _segmentation()["windows"]
        if row["split"] == split and int(row["horizon"]) in horizons
    ]


def _window_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row["symbol"]), int(row["horizon_bars"]), str(row["cutoff"]))


def _percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(float(v) for v in values if v is not None and not math.isnan(float(v)))
    if not clean:
        return None
    index = min(len(clean) - 1, max(0, round((pct / 100) * (len(clean) - 1))))
    return clean[index]


def _trimmed_mean(values: list[float], trim: float = 0.05) -> float | None:
    clean = sorted(float(v) for v in values if v is not None and not math.isnan(float(v)))
    if not clean:
        return None
    cut = int(len(clean) * trim)
    trimmed = clean[cut:len(clean) - cut] if len(clean) - 2 * cut > 0 else clean
    return mean(trimmed)


def _value_summary(values: list[float]) -> dict[str, Any]:
    return describe(values) | {"p95": _percentile(values, 95), "trimmed_mean_5pct": _trimmed_mean(values)}


def _read_artifact_frame(registry: ExperimentRegistry, experiment_id: str, artifact_type: str) -> pd.DataFrame | None:
    row = registry.connection.execute(
        "select relative_path from artifacts where experiment_id=? and artifact_type=?",
        (experiment_id, artifact_type),
    ).fetchone()
    if not row:
        return None
    path = RESULTS_DIR / row["relative_path"]
    if not path.exists():
        return None
    return pd.read_csv(path, compression="gzip")


def _metric_records(*, run_id: str | None = None, model_names: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    registry = ExperimentRegistry()
    try:
        params: list[Any] = []
        query = """
            select e.run_id, e.experiment_id, e.model_name, e.horizon_bars, e.symbol,
                   e.settings_json, s.exchange, s.cutoff, s.context_start, s.context_end,
                   s.future_start, s.future_end, s.purpose, m.metric_json, r.regime_json
            from experiments e
            left join metrics m on e.experiment_id=m.experiment_id
            left join regimes r on e.experiment_id=r.experiment_id
            left join experiment_specs s on e.experiment_id=s.experiment_id
        """
        if run_id:
            query += " left join executions x on e.experiment_id=x.experiment_id and x.run_id=? where (x.run_id=? or e.run_id=?)"
            params.extend([run_id, run_id, run_id])
        else:
            query += " where 1=1"
        if model_names:
            marks = ",".join("?" for _ in model_names)
            query += f" and e.model_name in ({marks})"
            params.extend(model_names)
        records: list[dict[str, Any]] = []
        for row in registry.connection.execute(query, params):
            if not row["metric_json"]:
                continue
            data = dict(row)
            metrics = json.loads(data.pop("metric_json"))
            regime_json = data.pop("regime_json", None)
            regime = json.loads(regime_json) if regime_json else {}
            settings = json.loads(data.pop("settings_json") or "{}")
            records.append({**data, **metrics, "settings": settings, "regime": regime})
        return records
    finally:
        registry.close()


def _candidate_id(settings: dict[str, Any]) -> str:
    if settings == canonical_settings():
        return "control_kronos_base_v1"
    return str(settings.get("phase1d_config_id") or hashlib.sha256(json.dumps(settings, sort_keys=True).encode("utf-8")).hexdigest()[:12])


def _group_by_candidate(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[_candidate_id(row.get("settings") or {})].append(row)
    return grouped


def _baseline_index(split: str) -> dict[tuple[str, int, str], dict[str, dict[str, Any]]]:
    run_id = f"phase1c_{split}"
    rows = _metric_records(run_id=run_id, model_names=BASELINES)
    index: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        index[_window_key(row)][row["model_name"]] = row
    return index


def _candidate_comparison(candidate_rows: list[dict[str, Any]], *, split: str, metric: str = "mae") -> dict[str, Any]:
    baselines = _baseline_index(split)
    by_key = {_window_key(row): row for row in candidate_rows}
    result: dict[str, Any] = {}
    for baseline in BASELINES:
        deltas: list[float] = []
        wins = losses = ties = 0
        for key, kronos in by_key.items():
            base = baselines.get(key, {}).get(baseline)
            if not base or kronos.get(metric) is None or base.get(metric) is None:
                continue
            delta = float(kronos[metric]) - float(base[metric])
            deltas.append(delta)
            if delta < 0:
                wins += 1
            elif delta > 0:
                losses += 1
            else:
                ties += 1
        result[baseline] = {
            "metric": metric,
            "n": len(deltas),
            "mean_delta": mean(deltas) if deltas else None,
            "median_delta": median(deltas) if deltas else None,
            "win_count": wins,
            "loss_count": losses,
            "tie_count": ties,
            "win_rate": wins / len(deltas) * 100 if deltas else None,
            "ci": bootstrap_ci(deltas),
        }
    means = [v["mean_delta"] for v in result.values() if v["mean_delta"] is not None]
    result["worst_delta"] = max(means) if len(means) == len(BASELINES) else None
    return result


def _rank_candidates(records: list[dict[str, Any]], *, split: str) -> list[dict[str, Any]]:
    ranked = []
    for config_id, rows in _group_by_candidate(records).items():
        comparison = _candidate_comparison(rows, split=split)
        ranked.append({
            "config_id": config_id,
            "n": len(rows),
            "comparison": comparison,
            "worst_delta": comparison["worst_delta"],
            "mean_win_rate": mean([v["win_rate"] for k, v in comparison.items() if k in BASELINES and v["win_rate"] is not None]) if comparison else None,
            "runtime_seconds": sum(float(row.get("inference_seconds") or 0) for row in rows),
        })
    ranked.sort(key=lambda item: (float("inf") if item["worst_delta"] is None else item["worst_delta"], -(item["mean_win_rate"] or 0)))
    return ranked


def phase1d_failure_diagnosis() -> dict[str, Any]:
    registry = ExperimentRegistry()
    records = registry.metric_records("phase1c_development")
    kronos_records = [row for row in records if row["model_name"] == "kronos"]
    baseline_records = [row for row in records if row["model_name"] in BASELINES]
    pair_groups: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in records:
        pair_groups[_window_key(row)][row["model_name"]] = row

    per_window = []
    step_errors: dict[int, list[float]] = defaultdict(list)
    by_horizon_returns: dict[int, list[dict[str, float]]] = defaultdict(list)
    continuity = []
    ranges = []
    session_groups: dict[str, list[float]] = defaultdict(list)
    ohlc = defaultdict(list)

    for row in kronos_records:
        prediction = _read_artifact_frame(registry, row["experiment_id"], "prediction")
        actual = _read_artifact_frame(registry, row["experiment_id"], "actual")
        context = _read_artifact_frame(registry, row["experiment_id"], "context_tail")
        if prediction is None or actual is None or context is None:
            continue
        prediction["timestamp"] = pd.to_datetime(prediction["timestamp"])
        actual["timestamp"] = pd.to_datetime(actual["timestamp"])
        context["timestamp"] = pd.to_datetime(context["timestamp"])
        joined = prediction.reset_index(drop=True).join(actual.reset_index(drop=True), lsuffix="_pred", rsuffix="_actual")
        last_close = float(context["close"].iloc[-1])
        pred_final = float(joined["close_pred"].iloc[-1])
        actual_final = float(joined["close_actual"].iloc[-1])
        pred_ret = (pred_final - last_close) / last_close
        actual_ret = (actual_final - last_close) / last_close
        horizon = int(row["horizon_bars"])
        abs_errors = (joined["close_pred"].astype(float) - joined["close_actual"].astype(float)).abs()
        for idx, err in enumerate(abs_errors, start=1):
            step_errors[idx].append(float(err))
        first_gap_minutes = (actual["timestamp"].iloc[0] - context["timestamp"].iloc[-1]).total_seconds() / 60
        future_internal_gaps = int((actual["timestamp"].diff().dropna().dt.total_seconds() > 5 * 60).sum())
        gap_group = "cross_session_or_gap" if first_gap_minutes > 5 or future_internal_gaps else "continuous_intraday"
        session_groups[gap_group].append(float(row["mae"]))
        predicted_range = float(joined["close_pred"].max() - joined["close_pred"].min())
        actual_range = float(joined["close_actual"].max() - joined["close_actual"].min())
        ranges.append({"horizon": horizon, "predicted_range": predicted_range, "actual_range": actual_range, "ratio": predicted_range / actual_range if actual_range else None})
        continuity.append({"horizon": horizon, "jump_pct": abs(float(joined["close_pred"].iloc[0]) - last_close) / last_close * 100})
        by_horizon_returns[horizon].append({"predicted_abs_return": abs(pred_ret), "actual_abs_return": abs(actual_ret), "predicted_return": pred_ret, "actual_return": actual_ret})
        for col in ("open_mae", "high_mae", "low_mae", "close_mae", "ohlc_aggregate_error", "volatility_error", "range_error"):
            if row.get(col) is not None:
                ohlc[col].append(float(row[col]))
        per_window.append({
            "symbol": row["symbol"],
            "horizon": horizon,
            "cutoff": row.get("cutoff"),
            "mae": row.get("mae"),
            "normalized_mae": row.get("normalized_mae"),
            "predicted_return": pred_ret,
            "actual_return": actual_ret,
            "predicted_abs_return": abs(pred_ret),
            "actual_abs_return": abs(actual_ret),
            "directional_match": row.get("directional_match"),
            "gap_group": gap_group,
            "regime": row.get("regime"),
        })
    registry.close()

    direction = Counter("up" if item["predicted_return"] >= 0 else "down" for item in per_window)
    actual_direction = Counter("up" if item["actual_return"] >= 0 else "down" for item in per_window)
    anatomy = Counter()
    anatomy_by_horizon: dict[int, Counter] = defaultdict(Counter)
    for key, models in pair_groups.items():
        if "kronos" not in models:
            continue
        wins = 0
        for baseline in BASELINES:
            if baseline in models and models["kronos"].get("mae") is not None and models[baseline].get("mae") is not None:
                wins += int(float(models["kronos"]["mae"]) < float(models[baseline]["mae"]))
        label = f"beats_{wins}_baselines"
        anatomy[label] += 1
        anatomy_by_horizon[key[1]][label] += 1

    magnitude_by_horizon = {}
    for horizon, rows in by_horizon_returns.items():
        pred_abs = [r["predicted_abs_return"] for r in rows]
        actual_abs = [r["actual_abs_return"] for r in rows]
        magnitude_by_horizon[str(horizon)] = {
            "mean_predicted_abs_return": mean(pred_abs),
            "mean_actual_abs_return": mean(actual_abs),
            "ratio": mean(pred_abs) / mean(actual_abs) if mean(actual_abs) else None,
            "predicted_abs_return": _value_summary(pred_abs),
            "actual_abs_return": _value_summary(actual_abs),
        }

    step_checkpoints = {str(step): _value_summary(values) for step, values in step_errors.items() if step in {1, 5, 10, 24, 50, 75, 120}}
    symbol_rank = sorted(
        [{"symbol": symbol, "mae": describe([float(r["mae"]) for r in rows if r.get("mae") is not None])} for symbol, rows in _group_items(per_window, "symbol").items()],
        key=lambda item: item["mae"]["mean"] if item["mae"]["mean"] is not None else float("inf"),
    )
    horizon_rank = {str(h): _candidate_comparison([r for r in kronos_records if int(r["horizon_bars"]) == h], split="development") for h in (24, 75, 120)}
    outlier_mae = [float(row["mae"]) for row in per_window if row.get("mae") is not None]
    worst_cases = sorted(per_window, key=lambda row: row.get("normalized_mae") or 0, reverse=True)[:15]
    baseline_count = len(baseline_records)

    payload = {
        "phase": PHASE,
        "source_run": "phase1c_development",
        "kronos_windows": len(kronos_records),
        "baseline_records": baseline_count,
        "a1_forecast_magnitude_bias": magnitude_by_horizon,
        "a2_directional_bias": {"predicted_distribution": dict(direction), "actual_distribution": dict(actual_direction)},
        "a3_error_by_forecast_depth": step_checkpoints,
        "a4_range_volatility_bias": {
            "range_ratio": _value_summary([r["ratio"] for r in ranges if r["ratio"] is not None]),
            "range_error": _value_summary(ohlc["range_error"]),
            "volatility_error": _value_summary(ohlc["volatility_error"]),
        },
        "a5_first_step_continuity": _value_summary([r["jump_pct"] for r in continuity]),
        "a6_shape_vs_price_level": {
            "correlation": _value_summary([float(r["correlation"]) for r in kronos_records if r.get("correlation") is not None]),
            "return_correlation": _value_summary([float(r["return_correlation"]) for r in kronos_records if r.get("return_correlation") is not None]),
            "directional_match_pct": mean([100.0 if r.get("directional_match") else 0.0 for r in kronos_records]),
        },
        "a7_horizon_specific_performance": horizon_rank,
        "a8_symbol_specific_performance": symbol_rank,
        "a9_regime_specific_performance": _regime_summary(per_window),
        "a10_session_gap_behavior": {group: _value_summary(values) for group, values in session_groups.items()},
        "a11_ohlc_volume_behavior": {key: _value_summary(values) for key, values in ohlc.items()},
        "a12_outlier_concentration": _value_summary(outlier_mae) | {"worst_cases": worst_cases},
        "a13_baseline_relative_anatomy": {
            "overall": dict(anatomy),
            "by_horizon": {str(k): dict(v) for k, v in anatomy_by_horizon.items()},
        },
        "facts": [
            "Phase 1C development artifacts contained 696 Kronos forecasts.",
            "Official KronosPredictor averaged multiple samples internally.",
            "Phase 1D diagnosis used stored predictions, actuals, and context tails only.",
        ],
        "hypotheses": [
            "Temperature/top_p reduction may help if predicted movement or volatility is too high.",
            "Shorter effective lookback may help if cross-session context adds noise for intraday Indian equities.",
            "Multiple samples may stabilize paths, but runtime cost must be tested carefully.",
        ],
        "experiments_to_test": [
            "Conservative temperature candidates at T=0.70 and T=0.85.",
            "Effective lookback candidates at 256, 320, and 400 bars.",
            "One limited sample_count=3 candidate only on early tournament rounds.",
        ],
    }
    _write_json(FAILURE_JSON, payload)
    _write_markdown(FAILURE_MD, _failure_markdown(payload))
    return payload


def _group_items(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key))].append(row)
    return grouped


def _regime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        regime = row.get("regime") or {}
        label = f"{regime.get('trend')}|{regime.get('volatility')}|{regime.get('open_close_zone')}"
        if row.get("mae") is not None:
            grouped[label].append(float(row["mae"]))
    return {label: _value_summary(values) for label, values in grouped.items()}


def _failure_markdown(payload: dict[str, Any]) -> str:
    return "\n".join([
        "# Phase 1D Failure Diagnosis",
        "",
        f"- Source run: `{payload['source_run']}`",
        f"- Kronos windows analyzed: {payload['kronos_windows']}",
        f"- Baseline records available: {payload['baseline_records']}",
        "",
        "## Facts",
        *[f"- {item}" for item in payload["facts"]],
        "",
        "## Magnitude Bias",
        "```json",
        json.dumps(payload["a1_forecast_magnitude_bias"], indent=2),
        "```",
        "",
        "## Direction Bias",
        "```json",
        json.dumps(payload["a2_directional_bias"], indent=2),
        "```",
        "",
        "## Horizon Performance",
        "```json",
        json.dumps(payload["a7_horizon_specific_performance"], indent=2),
        "```",
        "",
        "## Outlier Concentration",
        "```json",
        json.dumps(payload["a12_outlier_concentration"], indent=2, default=str),
        "```",
        "",
        "## Hypotheses",
        *[f"- {item}" for item in payload["hypotheses"]],
        "",
        "## Experiments To Test",
        *[f"- {item}" for item in payload["experiments_to_test"]],
    ])


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def phase1d_inference_audit() -> dict[str, Any]:
    data_issues = []
    split_issues = []
    artifact_issues = []
    for row in _segmentation()["windows"]:
        if row["split"] == "locked_test":
            continue
        frame, manifest, quality, _ = load_dataset(row["symbol"])
        if quality["status"] == "error":
            data_issues.append({"symbol": row["symbol"], "issue": "quality_error"})
        window = BenchmarkWindow(**row["window"])
        try:
            validate_window_bounds(frame, window)
            context, future = split_window(frame, window)
            if context["timestamp"].max() >= future["timestamp"].min():
                split_issues.append({"window_id": window.window_id, "issue": "future_leakage"})
        except Exception as error:
            split_issues.append({"window_id": row["window"]["window_id"], "issue": str(error)})

    registry = ExperimentRegistry()
    for record in registry.metric_records("phase1c_development"):
        if record["model_name"] != "kronos":
            continue
        prediction = _read_artifact_frame(registry, record["experiment_id"], "prediction")
        actual = _read_artifact_frame(registry, record["experiment_id"], "actual")
        if prediction is None or actual is None:
            artifact_issues.append({"experiment_id": record["experiment_id"], "issue": "missing prediction/actual artifact"})
            continue
        if len(prediction) != int(record["horizon_bars"]) or len(actual) != int(record["horizon_bars"]):
            artifact_issues.append({"experiment_id": record["experiment_id"], "issue": "artifact row count does not match horizon"})
        if list(pd.to_datetime(prediction["timestamp"]).astype(str)) != list(pd.to_datetime(actual["timestamp"]).astype(str)):
            artifact_issues.append({"experiment_id": record["experiment_id"], "issue": "prediction timestamps do not align with target timestamps"})
    registry.close()

    material_defect = bool(data_issues or split_issues or artifact_issues)
    payload = {
        "phase": PHASE,
        "material_implementation_defect": material_defect,
        "data_issues": data_issues[:50],
        "split_issues": split_issues[:50],
        "artifact_issues": artifact_issues[:50],
        "audit_findings": {
            "timestamp_timezone": "Data is canonicalized to Asia/Kolkata before segmentation.",
            "chronological_ordering": "Window validation confirms context ends before future begins.",
            "future_exclusion": "split_window raises if context reaches hidden future.",
            "pred_len": "Runner passes window.horizon_bars directly to adapter and KronosPredictor.",
            "y_timestamp": "Frozen benchmark future timestamps are passed directly to Kronos.",
            "sample_count": "Official Kronos source repeats sample_count paths and averages decoded outputs internally.",
            "lookback": "Phase 1C canonical context is 400 bars; Phase 1D can use shorter effective tail context through settings.",
            "max_context": "Official README states Kronos-small/base max_context is 512.",
        },
        "phase1c_scientifically_affected": material_defect,
        "recommendation": "Stop before tuning." if material_defect else "No material defect found; tuning may proceed on development data only.",
    }
    _write_json(AUDIT_JSON, payload)
    _write_markdown(AUDIT_MD, "\n".join([
        "# Phase 1D Inference Path Audit",
        "",
        f"- Material implementation defect: `{material_defect}`",
        f"- Data issues: {len(data_issues)}",
        f"- Split issues: {len(split_issues)}",
        f"- Artifact issues: {len(artifact_issues)}",
        "",
        "## Findings",
        "```json",
        json.dumps(payload["audit_findings"], indent=2),
        "```",
        "",
        f"Recommendation: {payload['recommendation']}",
    ]))
    return payload


def build_phase1d_subset(*, per_symbol_horizon: int = 2, output_json: Path = TUNING_SUBSET_JSON, output_md: Path = TUNING_SUBSET_MD) -> dict[str, Any]:
    windows = sorted(_selected_windows("development"), key=lambda row: (row["symbol"], int(row["horizon"]), row["window"]["cutoff_timestamp"]))
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in windows:
        grouped[(row["symbol"], int(row["horizon"]))].append(row)
    selected = []
    for key in sorted(grouped):
        rows = grouped[key]
        if len(rows) <= per_symbol_horizon:
            selected.extend(rows)
            continue
        positions = [round(i * (len(rows) - 1) / (per_symbol_horizon - 1)) for i in range(per_symbol_horizon)]
        selected.extend(rows[pos] for pos in sorted(set(positions)))
    window_ids = [row["window"]["window_id"] for row in selected]
    digest = hashlib.sha256(json.dumps({"seed": SEED, "window_ids": window_ids}, sort_keys=True).encode("utf-8")).hexdigest()
    payload = {
        "scientific_id": f"phase1d_tuning_subset_{digest[:16]}",
        "selection_seed": SEED,
        "split": "development",
        "count": len(selected),
        "window_ids": window_ids,
        "symbol_distribution": dict(Counter(row["symbol"] for row in selected)),
        "horizon_distribution": dict(Counter(str(row["horizon"]) for row in selected)),
        "regime_distribution": dict(Counter(f"{row['regime'].get('trend')}|{row['regime'].get('volatility')}|{row['regime'].get('open_close_zone')}" for row in selected)),
        "date_distribution": dict(Counter(str(pd.Timestamp(row["window"]["cutoff_timestamp"]).date()) for row in selected)),
        "dataset_hashes": sorted({row["dataset_hash"] for row in selected}),
    }
    _write_json(output_json, payload)
    _write_markdown(output_md, "\n".join([
        "# Phase 1D Tuning Subset",
        "",
        f"- Scientific ID: `{payload['scientific_id']}`",
        f"- Windows: {payload['count']}",
        f"- Selection seed: {SEED}",
        "- Source split: development only",
        "- Locked test touched: false",
        "",
        "## Distribution",
        "```json",
        json.dumps({k: payload[k] for k in ("symbol_distribution", "horizon_distribution", "regime_distribution")}, indent=2),
        "```",
    ]))
    return payload


def _repo_cached(repo_id: str) -> bool:
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir()
        return any(repo.repo_id == repo_id for repo in cache.repos)
    except Exception:
        return False


def phase1d_candidates() -> dict[str, Any]:
    base = [
        Candidate("control_kronos_base_v1", "Phase 1C control", canonical_settings(), "Immutable Phase 1C canonical settings; exact cache reuse expected."),
        Candidate("base_t085_p090_lb400_s1", "Base conservative T", {"phase1d_config_id": "base_t085_p090_lb400_s1", "temperature": 0.85, "top_k": 0, "top_p": 0.90, "sample_count": 1}, "Lower temperature tests whether Phase 1C over-moved paths."),
        Candidate("base_t070_p090_lb400_s1", "Base low T", {"phase1d_config_id": "base_t070_p090_lb400_s1", "temperature": 0.70, "top_k": 0, "top_p": 0.90, "sample_count": 1}, "More conservative sampling for volatility/magnitude bias."),
        Candidate("base_t085_p080_lb400_s1", "Base conservative nucleus", {"phase1d_config_id": "base_t085_p080_lb400_s1", "temperature": 0.85, "top_k": 0, "top_p": 0.80, "sample_count": 1}, "Tighter nucleus tests if noisy tail tokens hurt intraday accuracy."),
        Candidate("base_t085_p090_lb320_s1", "Base 320-bar context", {"phase1d_config_id": "base_t085_p090_lb320_s1", "temperature": 0.85, "top_k": 0, "top_p": 0.90, "sample_count": 1, "effective_lookback_bars": 320}, "Shorter context tests whether older cross-session bars hurt zero-shot inference."),
        Candidate("base_t085_p090_lb256_s1", "Base 256-bar context", {"phase1d_config_id": "base_t085_p090_lb256_s1", "temperature": 0.85, "top_k": 0, "top_p": 0.90, "sample_count": 1, "effective_lookback_bars": 256}, "Minimum planned context candidate within frozen 400-bar windows."),
        Candidate("base_t070_p080_lb320_s1", "Base compact conservative", {"phase1d_config_id": "base_t070_p080_lb320_s1", "temperature": 0.70, "top_k": 0, "top_p": 0.80, "sample_count": 1, "effective_lookback_bars": 320}, "Combines shorter context with conservative sampling; not a full Cartesian grid."),
        Candidate("base_t085_p090_lb400_s3", "Base averaged samples", {"phase1d_config_id": "base_t085_p090_lb400_s3", "temperature": 0.85, "top_k": 0, "top_p": 0.90, "sample_count": 3}, "Limited sample averaging candidate; runtime cost measured early only."),
    ]
    skipped = []
    if _repo_cached("NeoQuasar/Kronos-small"):
        base.append(Candidate(
            "small_t085_p090_lb400_s1",
            "Small official checkpoint",
            {"phase1d_config_id": "small_t085_p090_lb400_s1", "model_checkpoint": "NeoQuasar/Kronos-small", "tokenizer_checkpoint": "NeoQuasar/Kronos-Tokenizer-base", "temperature": 0.85, "top_k": 0, "top_p": 0.90, "sample_count": 1},
            "Official smaller model, tested only if already cached locally.",
        ))
    else:
        skipped.append({"config_id": "small_t085_p090_lb400_s1", "reason": "NeoQuasar/Kronos-small was not detected in local Hugging Face cache."})
    payload = {
        "phase": PHASE,
        "candidate_count": len(base),
        "skipped": skipped,
        "controls": ["control_kronos_base_v1"],
        "candidates": [asdict(item) for item in base],
        "excluded": [
            "512 lookback was excluded because frozen Phase 1B windows contain a 400-bar context contract.",
            "top_k variation was excluded pending evidence from failure diagnosis or official guidance.",
            "sample_count=5 was excluded from early rounds due runtime risk.",
        ],
    }
    _write_json(CANDIDATES_JSON, payload)
    _write_markdown(CANDIDATES_MD, "\n".join([
        "# Phase 1D Candidate Designs",
        "",
        f"- Candidate count: {payload['candidate_count']}",
        f"- Skipped candidates: {len(skipped)}",
        "- Design: high-information, non-Cartesian tournament",
        "",
        "## Candidates",
        "```json",
        json.dumps(payload["candidates"], indent=2),
        "```",
        "",
        "## Excluded",
        *[f"- {item}" for item in payload["excluded"]],
    ]))
    return payload


def _load_candidate_map() -> dict[str, Candidate]:
    if not CANDIDATES_JSON.exists():
        phase1d_candidates()
    payload = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    return {item["config_id"]: Candidate(**item) for item in payload["candidates"]}


def _subset_windows(per_symbol_horizon: int) -> list[dict[str, Any]]:
    temp_json = PHASE1D_STATE_DIR / f"subset_{per_symbol_horizon}.json"
    temp_md = PHASE1D_STATE_DIR / f"subset_{per_symbol_horizon}.md"
    payload = build_phase1d_subset(per_symbol_horizon=per_symbol_horizon, output_json=temp_json, output_md=temp_md)
    ids = set(payload["window_ids"])
    return [row for row in _selected_windows("development") if row["window"]["window_id"] in ids]


def _round_plan(round_name: str) -> tuple[list[Candidate], list[dict[str, Any]], str]:
    candidates = _load_candidate_map()
    if round_name == "round1":
        return list(candidates.values()), _subset_windows(2), ROUND_RUN_IDS["round1"]
    if round_name == "round2":
        prior = phase1d_round_report("round1")
        ids = [item["config_id"] for item in prior["ranking"][:3]]
        return [candidates[item] for item in ids], _subset_windows(4), ROUND_RUN_IDS["round2"]
    if round_name == "round3":
        prior = phase1d_round_report("round2")
        ids = [item["config_id"] for item in prior["ranking"][:2]]
        return [candidates[item] for item in ids], _selected_windows("development"), ROUND_RUN_IDS["round3"]
    if round_name == "validation":
        frozen = _load_frozen_policy()
        return [candidates[frozen["winner_config_id"]]], _selected_windows("validation"), ROUND_RUN_IDS["validation"]
    raise ValueError(f"Unknown Phase 1D round: {round_name}")


def run_phase1d_round(round_name: str, *, retry_failed: bool = False, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    audit = phase1d_inference_audit() if not AUDIT_JSON.exists() else json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    if audit.get("material_implementation_defect"):
        raise RuntimeError("Phase 1D tuning is blocked by a material implementation defect.")
    if not FAILURE_JSON.exists():
        phase1d_failure_diagnosis()
    if not TUNING_SUBSET_JSON.exists():
        build_phase1d_subset()
    if not CANDIDATES_JSON.exists():
        phase1d_candidates()

    candidates, windows, run_id = _round_plan(round_name)
    estimate = _runtime_estimate(candidates, windows, run_id)
    if dry_run:
        return {"round": round_name, "run_id": run_id, "estimate": estimate}

    registry = ExperimentRegistry()
    registry.record_run(run_id, {
        "run_id": run_id,
        "phase": PHASE,
        "round": round_name,
        "candidates": [asdict(item) for item in candidates],
        "windows": len(windows),
        "estimate": estimate,
        "locked_test_touched": False,
    }, "running")
    adapter = KronosForecastAdapter()
    executed = 0
    started = time.perf_counter()
    try:
        total = len(candidates) * len(windows)
        completed = 0
        for candidate in candidates:
            for row in windows:
                frame, manifest_dict, _, _ = load_dataset(row["symbol"])
                window = BenchmarkWindow(**row["window"])
                executed += int(run_model_experiment(
                    registry=registry,
                    run_id=run_id,
                    model_name="kronos",
                    adapter=adapter,
                    bars=frame,
                    manifest=_manifest_object(manifest_dict),
                    window=window,
                    settings=candidate.settings,
                    system_configuration_id=DEFAULT_SYSTEM_CONFIGURATION_ID,
                    purpose=f"phase1d_{round_name}",
                    force=force,
                    retry_failed=retry_failed,
                    adapter_name="kronos",
                ))
                completed += 1
                if completed % 12 == 0:
                    registry.log(run_id, None, "INFO", "phase1d_progress", f"{completed}/{total} forecast attempts completed.")
                    registry.connection.commit()
        status = "completed_with_errors" if registry.summary(run_id)["failed_count"] else "completed"
        registry.finish_run(run_id, status)
    except KeyboardInterrupt:
        registry.finish_run(run_id, "interrupted")
        registry.close()
        raise
    summary = registry.summary(run_id)
    registry.close()
    report = phase1d_round_report(round_name)
    return {
        "round": round_name,
        "run_id": run_id,
        "executed_new_forecasts": executed,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "summary": summary,
        "report": str(REPORTS_DIR / f"phase1d_{round_name}.md"),
        "best_config": report["ranking"][0]["config_id"] if report.get("ranking") else None,
    }


def _runtime_estimate(candidates: list[Candidate], windows: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    sample_multiplier = sum(int(c.settings.get("sample_count", 1)) for c in candidates)
    calls = len(candidates) * len(windows)
    sample_equivalent = len(windows) * sample_multiplier
    historical_seconds = 40.7
    return {
        "candidate_count": len(candidates),
        "window_count": len(windows),
        "planned_forecast_attempts": calls,
        "sample_count_multiplier_sum": sample_multiplier,
        "sample_equivalent_forecasts": sample_equivalent,
        "rough_runtime_hours_from_phase1c": round(sample_equivalent * historical_seconds / 3600, 2),
        "run_id": run_id,
    }


def phase1d_round_report(round_name: str) -> dict[str, Any]:
    run_id = ROUND_RUN_IDS[round_name]
    split = "validation" if round_name == "validation" else "development"
    records = _metric_records(run_id=run_id, model_names=("kronos",))
    ranking = _rank_candidates(records, split=split)
    payload = {
        "phase": PHASE,
        "round": round_name,
        "run_id": run_id,
        "split": split,
        "records": len(records),
        "ranking": ranking,
        "locked_test_touched": False,
    }
    _write_json(REPORTS_DIR / f"phase1d_{round_name}.json", payload)
    _write_markdown(REPORTS_DIR / f"phase1d_{round_name}.md", "\n".join([
        f"# Phase 1D {round_name.title()} Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Split: `{split}`",
        f"- Records: {len(records)}",
        "- Locked test touched: false",
        "",
        "## Ranking",
        "```json",
        json.dumps(ranking, indent=2, default=str),
        "```",
    ]))
    return payload


def freeze_phase1d_policy() -> dict[str, Any]:
    report = phase1d_round_report("round3")
    if not report["ranking"]:
        raise RuntimeError("Round 3 has no candidate records to freeze.")
    winner = report["ranking"][0]["config_id"]
    candidates = _load_candidate_map()
    payload = {
        "policy_id": "kronos_zero_shot_v2",
        "winner_config_id": winner,
        "selected_from": "phase1d_round3_development",
        "selection_objective": "minimize worst_delta against persistence, drift, momentum on paired MAE",
        "locked_test_touched": False,
        "horizon_policy": {str(h): asdict(candidates[winner]) for h in (24, 75, 120)},
        "development_result": report["ranking"][0],
        "dataset_hashes": sorted({row["dataset_hash"] for row in _selected_windows("development")}),
    }
    _write_json(REPORTS_DIR / "phase1d_optimized_kronos_development.json", payload)
    _write_markdown(REPORTS_DIR / "phase1d_optimized_kronos_development.md", "\n".join([
        "# Phase 1D Optimized Kronos Development",
        "",
        f"- Policy ID: `{payload['policy_id']}`",
        f"- Winner config: `{winner}`",
        "- Locked test touched: false",
        "",
        "## Development Result",
        "```json",
        json.dumps(payload["development_result"], indent=2, default=str),
        "```",
    ]))
    return payload


def _load_frozen_policy() -> dict[str, Any]:
    path = REPORTS_DIR / "phase1d_optimized_kronos_development.json"
    if not path.exists():
        return freeze_phase1d_policy()
    return json.loads(path.read_text(encoding="utf-8"))


def phase1d_validation_report() -> dict[str, Any]:
    payload = phase1d_round_report("validation")
    path_json = REPORTS_DIR / "phase1d_optimized_kronos_validation.json"
    path_md = REPORTS_DIR / "phase1d_optimized_kronos_validation.md"
    _write_json(path_json, payload)
    _write_markdown(path_md, "\n".join([
        "# Phase 1D Optimized Kronos Validation",
        "",
        "- One frozen validation pass only",
        "- Locked test touched: false",
        "",
        "## Validation Result",
        "```json",
        json.dumps(payload["ranking"], indent=2, default=str),
        "```",
    ]))
    return payload


def launch_phase1d_round(round_name: str, *, retry_failed: bool = False) -> dict[str, Any]:
    PHASE1D_LOG_DIR.mkdir(parents=True, exist_ok=True)
    pid_path = PHASE1D_STATE_DIR / f"{round_name}.pid"
    if pid_path.exists():
        old_pid = pid_path.read_text(encoding="utf-8").strip()
        if old_pid and _pid_alive(old_pid):
            return {"status": "already_tracked", "pid": old_pid, "pid_path": str(pid_path)}
    log_path = PHASE1D_LOG_DIR / f"{round_name}.log"
    command = [sys.executable, "-m", "research.cli", "phase1d-run-round", "--round", round_name]
    if retry_failed:
        command.append("--retry-failed")
    with log_path.open("a", encoding="utf-8") as log:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=log, creationflags=flags)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "launched", "pid": process.pid, "log_path": str(log_path), "pid_path": str(pid_path), "command": " ".join(command)}


def _pid_alive(pid: str) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, check=False)
            return pid in result.stdout
        return Path(f"/proc/{pid}").exists()
    except Exception:
        return False


def phase1d_status(run_id: str) -> dict[str, Any]:
    registry = ExperimentRegistry()
    try:
        summary = registry.summary(run_id)
        rows = registry.connection.execute(
            "select event,message,created_at from run_logs where run_id=? order by id desc limit 8",
            (run_id,),
        ).fetchall()
        return {"run_id": run_id, "summary": summary, "recent_logs": [dict(row) for row in rows]}
    finally:
        registry.close()
