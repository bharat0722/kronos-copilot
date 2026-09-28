"""Aggregate benchmark analysis."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def aggregate_rows(rows: list[object]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["status"] not in {"success", "succeeded"} or not row["metrics_json"]:
            continue
        by_model[row["model_name"]].append(json.loads(row["metrics_json"]))
    summary: dict[str, Any] = {}
    for model, metrics in by_model.items():
        maes = [float(item["mae"]) for item in metrics if item.get("mae") is not None]
        rmses = [float(item["rmse"]) for item in metrics if item.get("rmse") is not None]
        directions = [bool(item["directional_match"]) for item in metrics if item.get("directional_match") is not None]
        summary[model] = {
            "windows": len(metrics),
            "mean_mae": sum(maes) / len(maes) if maes else None,
            "mean_rmse": sum(rmses) / len(rmses) if rmses else None,
            "directional_match_pct": sum(directions) / len(directions) * 100 if directions else None,
        }
    if "kronos" in summary and "persistence" in summary:
        summary["kronos_vs_persistence"] = {
            "mean_mae_delta": summary["kronos"]["mean_mae"] - summary["persistence"]["mean_mae"]
            if summary["kronos"]["mean_mae"] is not None and summary["persistence"]["mean_mae"] is not None else None
        }
    return summary
