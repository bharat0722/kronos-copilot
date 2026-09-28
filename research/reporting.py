"""Human-readable benchmark report generation."""

from __future__ import annotations

import json
import html
from pathlib import Path

import pandas as pd

from .analysis import aggregate_rows
from .artifacts import write_json_artifact
from .config import MINIMUM_RESEARCH_N, REPORTS_DIR, RUNS_DIR
from .registry import ExperimentRegistry
from .stats import aggregate_metrics, paired_comparisons


def _case_chart(report_dir: Path, run_id: str, exp_id: str, label: str, metrics: dict[str, object], artifacts: list[dict[str, object]]) -> str:
    by_type = {str(item["artifact_type"]): item for item in artifacts if item["experiment_id"] == exp_id}
    root = report_dir.parents[2]
    series = []
    for kind, color, dash in (("context_tail", "#6b7280", ""), ("actual", "#111827", ""), ("prediction", "#0f766e", "6 4")):
        item = by_type.get(kind)
        if not item:
            continue
        path = root / str(item["relative_path"])
        if not path.exists():
            continue
        frame = pd.read_csv(path, compression="gzip")
        if "close" in frame:
            series.append((kind, color, dash, frame["close"].astype(float).tolist()))
    values = [value for _, _, _, points in series for value in points]
    width, height, pad = 760, 260, 28
    def polyline(points: list[float], offset: int = 0) -> str:
        if not points or not values:
            return ""
        low, high = min(values), max(values)
        span = high - low or 1.0
        total = max(sum(len(item[3]) for item in series) - 1, 1)
        coords = []
        for index, value in enumerate(points):
            x = pad + (offset + index) / total * (width - pad * 2)
            y = height - pad - (value - low) / span * (height - pad * 2)
            coords.append(f"{x:.1f},{y:.1f}")
        return " ".join(coords)
    offset = 0
    lines = []
    boundary_x = pad
    for kind, color, dash, points in series:
        if kind == "actual":
            boundary_x = pad + offset / max(sum(len(item[3]) for item in series) - 1, 1) * (width - pad * 2)
        lines.append(f'<polyline points="{polyline(points, offset)}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}" />')
        offset += len(points)
    case_dir = report_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / f"{exp_id}_{label}.html"
    path.write_text(
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{html.escape(label)} {html.escape(exp_id)}</title>"
        "<body style='font-family:Segoe UI,system-ui,sans-serif;max-width:860px;margin:24px auto;color:#111827'>"
        f"<h1>{html.escape(label.title())} Case</h1><p><code>{html.escape(exp_id)}</code></p>"
        "<svg viewBox='0 0 760 260' width='100%' role='img' aria-label='Context, prediction, and actual close paths'>"
        "<rect width='760' height='260' fill='#f8fafc'/><line x1='{0:.1f}' y1='20' x2='{0:.1f}' y2='240' stroke='#b45309' stroke-dasharray='4 4'/>".format(boundary_x)
        + "".join(lines)
        + "</svg>"
        "<p>Gray: context tail. Dashed green: model/baseline prediction. Black: hidden actual future. Vertical line: forecast boundary.</p>"
        f"<pre>{html.escape(json.dumps(metrics, indent=2, default=str))}</pre></body>",
        encoding="utf-8",
    )
    return str(path.relative_to(report_dir)).replace("\\", "/")


def generate_markdown_report(run_id: str, registry: ExperimentRegistry | None = None) -> Path:
    own = registry is None
    registry = registry or ExperimentRegistry()
    rows = registry.rows(run_id)
    records = registry.metric_records(run_id)
    summary = registry.summary(run_id)
    aggregate = aggregate_rows(rows)
    stats_summary = aggregate_metrics(records, "mae")
    paired = paired_comparisons(records, "mae")
    worst = []
    best = []
    for row in rows:
        if row["status"] in {"success", "succeeded"} and row["metrics_json"]:
            metrics = json.loads(row["metrics_json"])
            normalized = float(metrics.get("normalized_mae") or metrics.get("mae") or 0)
            worst.append((normalized, row["experiment_id"], row["model_name"], row["symbol"], row["horizon_bars"], metrics))
            best.append((normalized, row["experiment_id"], row["model_name"], row["symbol"], row["horizon_bars"], metrics))
    worst = sorted(worst, key=lambda item: item[0], reverse=True)[:5]
    best = sorted(best, key=lambda item: item[0])[:5]
    report_dir = RUNS_DIR / run_id / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    all_artifacts = registry.artifacts(run_id, limit=1000)
    failure_index = [
        {"category": "worst_normalized_mae", "experiment_id": exp_id, "model": model, "symbol": symbol, "horizon": horizon, "normalized_mae": value}
        for value, exp_id, model, symbol, horizon, _ in worst
    ]
    success_index = [
        {"category": "lowest_normalized_mae", "experiment_id": exp_id, "model": model, "symbol": symbol, "horizon": horizon, "normalized_mae": value}
        for value, exp_id, model, symbol, horizon, _ in best
    ]
    for item, source in zip(failure_index, worst):
        item["case_artifact"] = _case_chart(report_dir, run_id, str(item["experiment_id"]), "failure", source[-1], all_artifacts)
    for item, source in zip(success_index, best):
        item["case_artifact"] = _case_chart(report_dir, run_id, str(item["experiment_id"]), "success", source[-1], all_artifacts)
    write_json_artifact(run_id, "report/summary.json", {"summary": summary, "aggregate": aggregate, "statistics": stats_summary, "paired": paired})
    write_json_artifact(run_id, "report/failures_index.json", {"failures": failure_index})
    write_json_artifact(run_id, "report/success_index.json", {"successes": success_index})
    write_json_artifact(run_id, "report/artifacts_index.json", {"artifacts": all_artifacts})
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{run_id}.md"
    lines = [
        f"# Kronos Copilot Phase 1 Benchmark Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        "## Summary",
        f"- Experiments: {summary['experiment_count']}",
        f"- Success: {summary['success_count']}",
        f"- Failed: {summary['failed_count']}",
        "",
        "## Aggregate Metrics",
        "```json",
        json.dumps(aggregate, indent=2),
        "```",
        "",
        "## Statistical Summary",
        "```json",
        json.dumps(stats_summary, indent=2),
        "```",
        "",
        "## Paired Baseline Comparisons",
        "Negative MAE delta means Kronos beat the baseline on the same window.",
        "```json",
        json.dumps(paired, indent=2),
        "```",
        "",
        "## Small Sample Guardrail",
        f"Minimum research sample threshold: n >= {MINIMUM_RESEARCH_N}. Groups below this are marked INSUFFICIENT_SAMPLE and must not be used as winner claims.",
        "",
        "## Worst Cases By MAE",
    ]
    for value, exp_id, model, symbol, horizon, metrics in worst:
        lines.append(f"- `{model}` {symbol} horizon {horizon}: normalized MAE {value:.6f}, MAE {float(metrics.get('mae') or 0):.6f}, experiment `{exp_id}`")
    lines.append("")
    lines.append("## Success Cases By Normalized MAE")
    for value, exp_id, model, symbol, horizon, metrics in best:
        lines.append(f"- `{model}` {symbol} horizon {horizon}: normalized MAE {value:.6f}, MAE {float(metrics.get('mae') or 0):.6f}, experiment `{exp_id}`")
    lines.extend([
        "",
        "## Limitations",
        "- Smoke runs use synthetic data unless a registered real dataset is explicitly supplied.",
        "- Overlapping windows are correlated and should not be interpreted as independent observations.",
        "- Bootstrap intervals are deterministic but can overstate certainty for overlapping windows.",
        "- Kronos inference is stochastic where backend kernels are not strictly deterministic; seeds are recorded as best-effort reproducibility.",
        "- Phase 1A.2 reports session and calendar gaps but does not infer all exchange holidays.",
        "",
        "## Methodology Note",
        "Each experiment uses context bars at or before the cutoff and hides future bars until scoring. Baselines use context only. Overlapping windows are reported through stride settings and should not be treated as fully independent when stride is below horizon.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    (report_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    if own:
        registry.close()
    return path
