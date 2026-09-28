"""Research-only Phase 3: persisted paths -> frozen ensemble -> one validation pass.

Usage: python -m research.phase3 prepare | validate
No provider, model, network, or training code is imported.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
import pandas as pd

from .config import REGISTRY_PATH, REPORTS_DIR, RESULTS_DIR
from .metrics import close_metrics
from .stats import bootstrap_ci
from .technical_intelligence import analyze


WINNER = "base_t085_p090_lb256_s1"
MODELS = ("kronos", "persistence", "drift", "momentum")
HORIZONS = (24, 75, 120)
CONFIG = REPORTS_DIR / "phase3_frozen_ensemble.json"
DEV_REPORT = REPORTS_DIR / "phase3_ensemble_results.json"
VAL_REPORT = REPORTS_DIR / "phase3_validation_results.json"


def _registry() -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{REGISTRY_PATH.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _key(row: dict[str, Any]) -> tuple[str, int, str]:
    return str(row["symbol"]), int(row["horizon_bars"]), str(row["cutoff"])


def _metadata(connection: sqlite3.Connection, runs: tuple[str, ...]) -> list[dict[str, Any]]:
    marks = ",".join("?" for _ in runs)
    query = f"""select e.experiment_id,e.run_id,e.model_name,e.symbol,e.horizon_bars,
        e.status,e.settings_json,s.cutoff,s.dataset_hash,s.context_end,s.future_start,s.future_end,
        s.interval,s.session_policy,e.regime_json,a.artifact_type,a.relative_path,a.hash,a.rows
        from experiments e join experiment_specs s on e.experiment_id=s.experiment_id
        join artifacts a on e.experiment_id=a.experiment_id
        where e.run_id in ({marks}) and e.status='succeeded'"""
    by_id: dict[str, dict[str, Any]] = {}
    for raw in connection.execute(query, runs):
        row = dict(raw)
        experiment_id = row["experiment_id"]
        if experiment_id not in by_id:
            by_id[experiment_id] = {key: value for key, value in row.items()
                                   if key not in ("artifact_type", "relative_path", "hash", "rows")}
            by_id[experiment_id]["artifacts"] = {}
        by_id[experiment_id]["artifacts"][row["artifact_type"]] = {
            "path": row["relative_path"], "hash": row["hash"], "rows": int(row["rows"])}
    return list(by_id.values())


def _index(rows: list[dict[str, Any]], split: str) -> dict[tuple[str, int, str], dict[str, dict[str, Any]]]:
    index: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        run = row["run_id"]
        model = row["model_name"]
        if split == "development":
            if run.startswith("phase1d_"):
                if json.loads(row["settings_json"] or "{}").get("phase1d_config_id") != WINNER:
                    continue
                model = "kronos"
            elif run != "phase1c_development" or model not in MODELS[1:]:
                continue
        else:
            if run == "phase1d_validation":
                if json.loads(row["settings_json"] or "{}").get("phase1d_config_id") != WINNER:
                    continue
                model = "kronos"
            elif run not in ("phase1c_validation", "phase1b_real_pilot") or model not in MODELS[1:]:
                continue
        key = _key(row)
        if model in index[key] and run == "phase1b_real_pilot":
            continue
        if model in index[key]:
            raise ValueError(f"Duplicate saved {model} prediction: {key}")
        index[key][model] = row
    # A Phase 1B pilot baseline fills exactly one Phase 1C validation omission.
    if split == "validation":
        index = {key: group for key, group in index.items() if "kronos" in group}
    return index


def _verify_index(index: dict[tuple[str, int, str], dict[str, dict[str, Any]]], split: str) -> dict[str, Any]:
    expected = 696 if split == "development" else 252
    if len(index) != expected:
        raise ValueError(f"Expected {expected} {split} windows, found {len(index)}")
    fallback = []
    for key, group in index.items():
        if set(group) != set(MODELS):
            raise ValueError(f"Missing persisted prediction for {key}: {set(MODELS)-set(group)}")
        anchor = group["kronos"]
        for model, record in group.items():
            if any(record[field] != anchor[field] for field in
                   ("dataset_hash", "cutoff", "context_end", "future_start", "future_end", "interval", "session_policy")):
                raise ValueError(f"Provenance mismatch for {key}, {model}")
            artifacts = record["artifacts"]
            if not {"prediction", "actual", "context_tail"}.issubset(artifacts):
                raise ValueError(f"Missing artifacts for {key}, {model}")
            if artifacts["prediction"]["rows"] != key[1] or artifacts["actual"]["rows"] != key[1]:
                raise ValueError(f"Incorrect artifact length for {key}, {model}")
            if not all((RESULTS_DIR / a["path"]).is_file() for a in artifacts.values()):
                raise ValueError(f"Missing artifact file for {key}, {model}")
            if record["run_id"] == "phase1b_real_pilot":
                fallback.append((key, model))
    return {"windows": len(index), "horizons": dict(Counter(key[1] for key in index)),
            "dataset_hashes": sorted({group["kronos"]["dataset_hash"] for group in index.values()}),
            "pilot_fallback": sorted({str(key) for key, _ in fallback})}


def _frame(record: dict[str, Any], kind: str) -> pd.DataFrame:
    info = record["artifacts"][kind]
    path = RESULTS_DIR / info["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != info["hash"]:
        raise ValueError(f"Stored artifact hash mismatch: {path}")
    frame = pd.read_csv(path, compression="gzip")
    if len(frame) != info["rows"]:
        raise ValueError(f"Stored artifact row mismatch: {path}")
    return frame


def _load(index: dict[tuple[str, int, str], dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for key in sorted(index):
        group = index[key]
        actual = _frame(group["kronos"], "actual")
        context = _frame(group["kronos"], "context_tail")
        technical = analyze(context)
        if pd.Timestamp(technical["as_of"]) != pd.Timestamp(key[2]):
            raise ValueError(f"Context leaks beyond or ends before cutoff: {key}")
        times = pd.to_datetime(actual["timestamp"], utc=True)
        if times.isna().any() or not times.is_monotonic_increasing or times.duplicated().any():
            raise ValueError(f"Invalid actual timestamps: {key}")
        paths = []
        for model in MODELS:
            prediction = _frame(group[model], "prediction")
            if not pd.to_datetime(prediction["timestamp"], utc=True).equals(times):
                raise ValueError(f"Prediction timestamps do not match actual: {key}, {model}")
            if group[model]["run_id"] == "phase1b_real_pilot":
                pilot_actual = _frame(group[model], "actual")
                pilot_context = _frame(group[model], "context_tail")
                if not np.array_equal(pilot_actual["close"].to_numpy(), actual["close"].to_numpy()) or \
                        float(pilot_context["close"].iloc[-1]) != float(context["close"].iloc[-1]):
                    raise ValueError(f"Pilot fallback target/context mismatch: {key}, {model}")
            paths.append(pd.to_numeric(prediction["close"], errors="raise").to_numpy(dtype=float))
        matrix = np.stack(paths, axis=-1)
        truth = pd.to_numeric(actual["close"], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(matrix).all() or not np.isfinite(truth).all() or (matrix <= 0).any() or (truth <= 0).any():
            raise ValueError(f"Invalid saved price: {key}")
        last = float(context["close"].iloc[-1])
        result.append({"key": key, "actual": actual, "context": context, "paths": matrix,
                       "truth": truth, "last": last, "technical": technical,
                       "regime": technical["regime"]})
    return result


def _weights(rows: list[dict[str, Any]]) -> list[float]:
    # A coarse simplex grid limits tuning freedom on overlapping windows.
    paths = np.stack([row["paths"] for row in rows])
    actual = np.stack([row["truth"] for row in rows])
    scale = np.array([row["last"] for row in rows])[:, None]
    best = (math.inf, None)
    for a, b, c in itertools.product(range(11), repeat=3):
        d = 10 - a - b - c
        if d < 0:
            continue
        vector = np.array([a, b, c, d], dtype=float) / 10
        score = float(np.mean(np.abs(np.einsum("nhm,m->nh", paths, vector) - actual) / scale))
        candidate = (round(score, 12), tuple(-vector))
        if best[1] is None or candidate < best[0]:
            best = (candidate, vector)
    return [float(x) for x in best[1]]


def _direction(value: float) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


def _decision(row: dict[str, Any], weights: dict[int, list[float]], threshold: float,
              require_agreement: bool) -> str:
    vector = np.array(weights[row["key"][1]])
    predicted = float(row["paths"][-1] @ vector)
    direction = _direction(predicted - row["last"])
    magnitude = abs(predicted / row["last"] - 1) * 100
    if direction == 0 or magnitude < threshold:
        return "NO_STRONG_EDGE"
    if require_agreement:
        kronos_direction = _direction(float(row["paths"][-1, 0]) - row["last"])
        technical = row["technical"]
        vote = (1 if technical["trend"] == "bullish" else -1 if technical["trend"] == "bearish" else 0)
        vote += (1 if technical["momentum"] == "bullish" else -1 if technical["momentum"] == "bearish" else 0)
        if kronos_direction != direction or vote * direction <= 0:
            return "NO_STRONG_EDGE"
    return "BULLISH" if direction > 0 else "BEARISH"


def _policy_stats(rows: list[dict[str, Any]], weights: dict[int, list[float]],
                  threshold: float, agreement: bool) -> dict[str, Any]:
    chosen = [(row, _decision(row, weights, threshold, agreement)) for row in rows]
    active = [(row, decision) for row, decision in chosen if decision != "NO_STRONG_EDGE"]
    hits = sum(_direction(float(row["truth"][-1]) - row["last"]) ==
               (1 if decision == "BULLISH" else -1) for row, decision in active)
    return {"n": len(rows), "actionable": len(active), "hits": hits,
            "coverage_pct": 100 * len(active) / len(rows) if rows else None,
            "directional_hit_rate_pct": 100 * hits / len(active) if active else None}


def _wilson_lower(hits: int, n: int) -> float:
    if not n:
        return 0.0
    z = 1.96
    p = hits / n
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p)+z*z/(4*n))/n)) / (1+z*z/n)


def _choose_policy(rows: list[dict[str, Any]], weights: dict[int, list[float]]) -> dict[str, Any]:
    candidates = []
    for threshold in (0.0, 0.1, 0.2, 0.3, 0.5):
        for agreement in (False, True):
            stats = _policy_stats(rows, weights, threshold, agreement)
            if stats["actionable"] >= 50 and stats["coverage_pct"] >= 25:
                candidates.append((_wilson_lower(stats["hits"], stats["actionable"]),
                                   stats["coverage_pct"], -threshold, not agreement,
                                   threshold, agreement, stats))
    if not candidates:
        return {"threshold_pct": 0.0, "require_agreement": False,
                "calibration": _policy_stats(rows, weights, 0.0, False), "selection": "fallback"}
    chosen = max(candidates)
    return {"threshold_pct": chosen[4], "require_agreement": chosen[5],
            "calibration": chosen[6], "selection": "maximum Wilson lower bound; minimum 25% coverage and 50 actions"}


METRICS = ("mae", "normalized_mae", "rmse", "mape", "smape", "mase", "final_error",
           "total_return_error", "range_error", "volatility_error")


def _evaluate(rows: list[dict[str, Any]], weights: dict[int, list[float]],
              policy: dict[str, Any]) -> dict[str, Any]:
    records = []
    for row in rows:
        preds = {model: row["paths"][:, i] for i, model in enumerate(MODELS)}
        preds["ensemble"] = row["paths"] @ np.array(weights[row["key"][1]])
        results = {}
        for model, prices in preds.items():
            frame = pd.DataFrame({"timestamp": row["actual"]["timestamp"], "close": prices})
            results[model] = close_metrics(frame, row["actual"], row["context"])
        records.append({"symbol": row["key"][0], "horizon": row["key"][1], "cutoff": row["key"][2],
                        "regime": row["regime"], "metrics": results,
                        "decision": _decision(row, weights, policy["threshold_pct"], policy["require_agreement"]),
                        "actual_direction": _direction(float(row["truth"][-1]) - row["last"])})

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        means = {model: {metric: mean(float(r["metrics"][model][metric]) for r in group
                                       if r["metrics"][model][metric] is not None)
                         for metric in METRICS if any(r["metrics"][model][metric] is not None for r in group)}
                 for model in (*MODELS, "ensemble")}
        comparisons = {}
        for model in MODELS:
            deltas = [r["metrics"]["ensemble"]["mae"] - r["metrics"][model]["mae"] for r in group]
            comparisons[model] = {"mean_mae_delta": mean(deltas), "wins": sum(x < 0 for x in deltas),
                                  "losses": sum(x > 0 for x in deltas), "ties": sum(x == 0 for x in deltas),
                                  "win_rate_pct": 100 * sum(x < 0 for x in deltas) / len(deltas),
                                  "bootstrap_ci": bootstrap_ci(deltas)}
        active = [r for r in group if r["decision"] != "NO_STRONG_EDGE"]
        hits = sum((1 if r["decision"] == "BULLISH" else -1) == r["actual_direction"] for r in active)
        direction = {model: 100 * sum(bool(r["metrics"][model]["directional_match"]) for r in group) / len(group)
                     for model in (*MODELS, "ensemble")}
        return {"n": len(group), "mean_metrics": means, "directional_hit_rate_pct": direction,
                "paired_mae": comparisons, "policy": {"actions": len(active), "hits": hits,
                    "coverage_pct": 100 * len(active) / len(group),
                    "directional_hit_rate_pct": 100 * hits / len(active) if active else None}}

    return {"overall": summarize(records),
            "by_horizon": {str(h): summarize([r for r in records if r["horizon"] == h]) for h in HORIZONS},
            "by_symbol": {s: summarize([r for r in records if r["symbol"] == s]) for s in sorted({r["symbol"] for r in records})},
            "by_regime": {s: summarize([r for r in records if r["regime"] == s]) for s in sorted({r["regime"] for r in records})},
            "warnings": ["Windows overlap; naive window-level bootstrap intervals are descriptive, not independent-trial significance tests.",
                         "All results use historical persisted paths; no new forecasts or training were run."]}


def _write(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen Phase 3 artifact: {path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", "", "Research-only, persisted predictions. No inference or training.", ""]
    if "status" in payload:
        lines.append(f"Status: **{payload['status']}**")
    if "provenance" in payload:
        lines.append(f"Windows: {payload['provenance']['windows']}; {len(payload['provenance']['dataset_hashes'])} immutable symbol-level dataset hashes recorded in the JSON report.")
        if payload["provenance"]["pilot_fallback"]:
            lines.append("The one missing Phase 1C baseline trio came from the matching persisted Phase 1B pilot, not a new prediction.")
    results = payload.get("results")
    if results:
        lines += ["", "## Overall and horizons", "",
                  "| Group | N | Ensemble MAE | Persistence MAE | Drift MAE | Momentum MAE | Kronos MAE | Policy hit | Coverage |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, item in [("Overall", results["overall"]), *[(f"Horizon {h}", x) for h, x in results["by_horizon"].items()]]:
            m = item["mean_metrics"]
            p = item["policy"]
            lines.append(f"| {name} | {item['n']} | {m['ensemble']['mae']:.4f} | {m['persistence']['mae']:.4f} | {m['drift']['mae']:.4f} | {m['momentum']['mae']:.4f} | {m['kronos']['mae']:.4f} | {p['directional_hit_rate_pct']:.1f}% | {p['coverage_pct']:.1f}% |")
        overall = results["overall"]
        lines += ["", "## Paired overall MAE", "", "| Comparator | Mean delta | 95% bootstrap interval | Wins / losses / ties |",
                  "| --- | ---: | ---: | ---: |"]
        for model, pair in overall["paired_mae"].items():
            ci = pair["bootstrap_ci"]
            lines.append(f"| {model} | {pair['mean_mae_delta']:+.4f} | [{ci['low']:+.4f}, {ci['high']:+.4f}] | {pair['wins']} / {pair['losses']} / {pair['ties']} |")
        lines += ["", "Negative deltas favor the ensemble. Intervals are descriptive because evaluation windows overlap.",
                  "", "## Direction", "",
                  f"All-window ensemble hit rate: {overall['directional_hit_rate_pct']['ensemble']:.1f}%; persistence: {overall['directional_hit_rate_pct']['persistence']:.1f}%.",
                  f"Confidence gate: {overall['policy']['hits']}/{overall['policy']['actions']} correct, {overall['policy']['directional_hit_rate_pct']:.1f}% hit rate at {overall['policy']['coverage_pct']:.1f}% coverage.",
                  "", "## Symbols and technical regimes", "",
                  "| Group | N | Ensemble MAE | Persistence MAE | Gate hits/actions | Coverage |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for section in ("by_symbol", "by_regime"):
            for name, item in results[section].items():
                p = item["policy"]
                hit = f"{p['hits']}/{p['actions']} ({p['directional_hit_rate_pct']:.1f}%)" if p["directional_hit_rate_pct"] is not None else "0/0 (n/a)"
                lines.append(f"| {name} | {item['n']} | {item['mean_metrics']['ensemble']['mae']:.4f} | {item['mean_metrics']['persistence']['mae']:.4f} | {hit} | {p['coverage_pct']:.1f}% |")
        lines += ["", "Recomputed close metrics, paired intervals, and per-group comparisons are in the JSON report. MASE uses the saved 80-bar context tail, not the original full 400-bar research context.",
                  "The technical regime taxonomy is derived from the saved 80-bar context tail; rare regimes and low-action symbol rows are not reliable evidence of directional edge.",
                  "", *[f"- {warning}" for warning in results["warnings"]]]
    return "\n".join(lines) + "\n"


def render_saved_reports() -> None:
    """Format already persisted results; never re-evaluate or open prediction paths."""
    for source, name in ((DEV_REPORT, "Phase 3 development ensemble"),
                         (VAL_REPORT, "Phase 3 single validation pass")):
        if source.exists():
            result = json.loads(source.read_text(encoding="utf-8"))
            source.with_suffix(".md").write_text(_markdown(name, result), encoding="utf-8")
    technical = json.loads((REPORTS_DIR / "phase3_technical_intelligence.json").read_text(encoding="utf-8"))
    lines = ["# Phase 3 technical intelligence", "", "Historical-only indicators; no LLM calculations or model inference.", "",
             f"Analyzed development windows: {technical['window_count']}.", "", "## Definitions", ""]
    lines += [f"- **{name}:** {description}." for name, description in technical["definitions"].items()]
    lines += ["", "## Regimes", "", technical["regime_policy"] + ".", "",
              "| Regime | Development windows |", "| --- | ---: |"]
    lines += [f"| {name} | {count} |" for name, count in sorted(technical["regime_counts"].items())]
    lines += ["", "Each indicator returns value, signal, strength (0-1), and reason. Signals are descriptive research features, not calibrated probabilities.",
              "EMA and Wilder-style values use the saved 80-bar context tail, so longer-history initialization may differ. No future bars enter the indicator calculation."]
    (REPORTS_DIR / "phase3_technical_intelligence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare() -> None:
    if CONFIG.exists() or DEV_REPORT.exists():
        raise FileExistsError("Phase 3 development is already frozen; refusing to refit.")
    with _registry() as connection:
        index = _index(_metadata(connection, ("phase1c_development", "phase1d_round1_v2",
                                               "phase1d_round2", "phase1d_round3")), "development")
    provenance = _verify_index(index, "development")
    rows = _load(index)
    fit, calibration = [], []
    for horizon in HORIZONS:
        group = sorted((row for row in rows if row["key"][1] == horizon), key=lambda r: r["key"][2])
        cutoffs = sorted({row["key"][2] for row in group})
        boundary = cutoffs[max(1, int(len(cutoffs) * 0.7))]
        fit += [row for row in group if row["key"][2] < boundary]
        calibration += [row for row in group if row["key"][2] >= boundary]
    weights = {h: _weights([row for row in fit if row["key"][1] == h]) for h in HORIZONS}
    policy = _choose_policy(calibration, weights)
    frozen = {"version": "phase3_dev_frozen_v1", "source": "persisted Phase 1C baselines + Phase 1D winner",
              "winner": WINNER, "model_order": MODELS, "weights": weights, "policy": policy,
              "fit_windows": len(fit), "calibration_windows": len(calibration),
              "selection_rule": "10% simplex grid minimizes mean development normalized path MAE; chronological 70/30 fit/calibration split per horizon",
              "provenance": provenance, "locked_test_accesses": 0}
    _write(CONFIG, frozen)
    result = {"status": "FROZEN_DEVELOPMENT", "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
              "provenance": provenance, "fit_windows": len(fit), "calibration_windows": len(calibration),
              "weights": weights, "policy": policy, "results": _evaluate(rows, weights, policy)}
    _write(DEV_REPORT, result)
    (REPORTS_DIR / "phase3_ensemble_results.md").write_text(_markdown("Phase 3 development ensemble", result), encoding="utf-8")
    technical = {"status": "PASS", "module": "research.technical_intelligence", "window_count": len(rows),
                 "regime_counts": dict(Counter(row["regime"] for row in rows)),
                 "definitions": {"EMA": "20/50 spans, adjust=False", "SMA": "20/50 arithmetic rolling means",
                     "RSI": "14-bar Wilder-style exponential smoothing", "MACD": "12/26 EMA minus 9-bar signal",
                     "Bollinger": "20-bar mean +/- two population standard deviations", "ATR": "14-bar Wilder-smoothed true range",
                     "ROC": "10-bar close return in percent", "volume_spike": "latest volume / 20-bar mean"},
                 "regime_policy": "ATR/close >= 1.5% high, <= 0.3% low; else aligned EMA50/EMA20 trend and RSI/ROC/MACD momentum, otherwise sideways",
                 "historical_only": True}
    _write(REPORTS_DIR / "phase3_technical_intelligence.json", technical)
    (REPORTS_DIR / "phase3_technical_intelligence.md").write_text(
        "# Phase 3 technical intelligence\n\n" + json.dumps(technical, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"development_windows": len(rows), "weights": weights, "policy": policy,
                      "ensemble_mae": result["results"]["overall"]["mean_metrics"]["ensemble"]["mae"]}))


def validate() -> None:
    if VAL_REPORT.exists() or (REPORTS_DIR / "phase3_validation_results.md").exists():
        raise FileExistsError("Validation already evaluated; refusing to repeat.")
    if not CONFIG.exists() or not DEV_REPORT.exists():
        raise FileNotFoundError("Frozen development config and report required before validation.")
    frozen = json.loads(CONFIG.read_text(encoding="utf-8"))
    development = json.loads(DEV_REPORT.read_text(encoding="utf-8"))
    if hashlib.sha256(CONFIG.read_bytes()).hexdigest() != development["config_sha256"]:
        raise ValueError("Frozen config changed after development reporting.")
    with _registry() as connection:
        index = _index(_metadata(connection, ("phase1c_validation", "phase1d_validation", "phase1b_real_pilot")), "validation")
    provenance = _verify_index(index, "validation")
    if provenance["dataset_hashes"] != frozen["provenance"]["dataset_hashes"]:
        raise ValueError("Validation dataset identity differs from development.")
    rows = _load(index)
    weights = {int(k): v for k, v in frozen["weights"].items()}
    result = {"status": "SINGLE_VALIDATION_PASS", "config_sha256": development["config_sha256"],
              "provenance": provenance, "weights": weights, "policy": frozen["policy"],
              "results": _evaluate(rows, weights, frozen["policy"]),
              "note": "One missing Phase 1C validation baseline trio was sourced from the matching persisted Phase 1B pilot; no prediction was recomputed."}
    _write(VAL_REPORT, result)
    (REPORTS_DIR / "phase3_validation_results.md").write_text(_markdown("Phase 3 single validation pass", result), encoding="utf-8")
    print(json.dumps({"validation_windows": len(rows), "ensemble_mae": result["results"]["overall"]["mean_metrics"]["ensemble"]["mae"],
                      "policy": result["results"]["overall"]["policy"]}))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("prepare", "validate", "render"):
        raise SystemExit("Usage: python -m research.phase3 prepare|validate|render")
    {"prepare": prepare, "validate": validate, "render": render_saved_reports}[sys.argv[1]]()
