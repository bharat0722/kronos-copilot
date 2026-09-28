"""Phase 1B real NSE pilot dataset acquisition, segmentation, locking, and pilot runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from .adapters.kronos_adapter import FakeForecastAdapter, KronosForecastAdapter
from .baselines import BASELINES
from .config import DATASET_DIR, METRICS_VERSION, PREPROCESSING_VERSION, REGIME_VERSION, ensure_research_dirs
from .datasets import build_manifest, canonicalize_bars, dataset_hash, quality_report
from .provenance import environment_info, git_info, model_provenance
from .registry import ExperimentRegistry
from .reporting import generate_markdown_report
from .runner import BaselineAdapter, run_model_experiment
from .stats import overlap_summary
from .windows import generate_windows, split_window


PHASE1B_ROOT = DATASET_DIR / "phase1b_pilot"
RAW_DIR = PHASE1B_ROOT / "raw"
MANIFEST_DIR = PHASE1B_ROOT / "manifests"
REPORT_DIR = PHASE1B_ROOT / "reports"
SPLIT_PATH = PHASE1B_ROOT / "segmentation.json"
LOCK_PATH = PHASE1B_ROOT / "locked_subset.json"
COLLECTION_PATH = PHASE1B_ROOT / "collection_manifest.json"

PILOT_UNIVERSE = [
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries Limited", "sector": "Energy / Conglomerate"},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services Limited", "sector": "Information Technology"},
    {"symbol": "INFY.NS", "name": "Infosys Limited", "sector": "Information Technology"},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank Limited", "sector": "Private Bank"},
    {"symbol": "ICICIBANK.NS", "name": "ICICI Bank Limited", "sector": "Private Bank"},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "sector": "Public Bank"},
    {"symbol": "HINDUNILVR.NS", "name": "Hindustan Unilever Limited", "sector": "FMCG"},
    {"symbol": "ITC.NS", "name": "ITC Limited", "sector": "FMCG"},
    {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel Limited", "sector": "Telecom"},
    {"symbol": "LT.NS", "name": "Larsen & Toubro Limited", "sector": "Industrials"},
    {"symbol": "SUNPHARMA.NS", "name": "Sun Pharmaceutical Industries Limited", "sector": "Pharma"},
    {"symbol": "MARUTI.NS", "name": "Maruti Suzuki India Limited", "sector": "Auto"},
]


@dataclass(frozen=True)
class DatasetRef:
    symbol: str
    sector: str
    name: str
    data_path: str
    manifest_path: str
    quality_path: str
    dataset_id: str
    dataset_hash: str
    rows: int
    start: str
    end: str
    quality_status: str


def _now() -> str:
    return pd.Timestamp.now(tz=timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_from_yahoo(symbol: str, *, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    frame = ticker.history(period=period, interval=interval, auto_adjust=False, actions=False, prepost=False)
    if frame.empty:
        raise RuntimeError(f"Yahoo Finance returned no data for {symbol}.")
    frame = frame.reset_index()
    timestamp_column = "Datetime" if "Datetime" in frame.columns else "Date"
    data = pd.DataFrame({
        "timestamp": frame[timestamp_column],
        "open": frame["Open"],
        "high": frame["High"],
        "low": frame["Low"],
        "close": frame["Close"],
        "volume": frame["Volume"],
    })
    data["amount"] = data["close"].astype(float) * data["volume"].astype(float)
    return canonicalize_bars(data).dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)


def acquire_pilot_datasets(*, period: str = "60d", interval: str = "5m", limit: int = 12) -> dict[str, Any]:
    ensure_research_dirs()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    acquired_at = _now()
    refs: list[DatasetRef] = []
    failures: list[dict[str, str]] = []
    for item in PILOT_UNIVERSE[:limit]:
        symbol = item["symbol"]
        try:
            frame = _frame_from_yahoo(symbol, period=period, interval=interval)
            data_path = RAW_DIR / f"{symbol.replace('.', '_')}.csv.gz"
            frame.to_csv(data_path, index=False, compression="gzip")
            persisted = canonicalize_bars(pd.read_csv(data_path, compression="gzip"))
            report = quality_report(persisted)
            manifest = build_manifest(
                persisted,
                symbol=symbol,
                exchange="NSE",
                interval=interval,
                source=f"yfinance:{symbol}:{period}:{interval}",
                source_type="yahoo_finance",
                provider_name="Yahoo Finance via yfinance",
                provider_version=getattr(yf, "__version__", "unknown"),
                source_url=f"https://finance.yahoo.com/quote/{symbol}",
                local_source_path=f"raw/{symbol.replace('.', '_')}.csv.gz",
                currency="INR",
                acquired_at=acquired_at,
                notes=f"Phase 1B pilot NSE equity dataset; sector={item['sector']}",
            )
            manifest_path = MANIFEST_DIR / f"{symbol.replace('.', '_')}_manifest.json"
            quality_path = MANIFEST_DIR / f"{symbol.replace('.', '_')}_quality.json"
            persisted.to_csv(data_path, index=False, compression="gzip")
            _write_json(manifest_path, manifest.as_dict())
            _write_json(quality_path, report.as_dict())
            refs.append(DatasetRef(
                symbol=symbol,
                sector=item["sector"],
                name=item["name"],
                data_path=str(data_path.relative_to(PHASE1B_ROOT)).replace("\\", "/"),
                manifest_path=str(manifest_path.relative_to(PHASE1B_ROOT)).replace("\\", "/"),
                quality_path=str(quality_path.relative_to(PHASE1B_ROOT)).replace("\\", "/"),
                dataset_id=manifest.dataset_id,
                dataset_hash=manifest.dataset_hash_full,
                rows=len(frame),
                start=manifest.start_timestamp,
                end=manifest.end_timestamp,
                quality_status=report.status,
            ))
        except Exception as error:
            failures.append({"symbol": symbol, "error": str(error).splitlines()[0][:500]})
    collection = {
        "collection_id": f"phase1b_pilot_{hashlib.sha256(acquired_at.encode('utf-8')).hexdigest()[:12]}",
        "created_at": acquired_at,
        "period": period,
        "interval": interval,
        "provider": "Yahoo Finance via yfinance",
        "provider_version": getattr(yf, "__version__", "unknown"),
        "symbols_requested": len(PILOT_UNIVERSE[:limit]),
        "symbols_acquired": len(refs),
        "datasets": [asdict(ref) for ref in refs],
        "failures": failures,
        "notes": "Generated market data is runtime research data and intentionally ignored by Git.",
    }
    _write_json(COLLECTION_PATH, collection)
    return collection


def load_collection() -> dict[str, Any]:
    if not COLLECTION_PATH.exists():
        raise FileNotFoundError("No Phase 1B collection manifest found. Run acquire-data first.")
    return _read_json(COLLECTION_PATH)


def load_dataset(symbol: str) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], dict[str, Any]]:
    collection = load_collection()
    ref = next((item for item in collection["datasets"] if item["symbol"] == symbol), None)
    if not ref:
        raise ValueError(f"Symbol is not in the Phase 1B collection: {symbol}")
    frame = canonicalize_bars(pd.read_csv(PHASE1B_ROOT / ref["data_path"], compression="gzip"))
    manifest = _read_json(PHASE1B_ROOT / ref["manifest_path"])
    quality = _read_json(PHASE1B_ROOT / ref["quality_path"])
    return frame, manifest, quality, ref


def validate_collection() -> dict[str, Any]:
    collection = load_collection()
    reports = []
    for ref in collection["datasets"]:
        frame, manifest, quality, _ = load_dataset(ref["symbol"])
        current_hash = dataset_hash(frame)
        reports.append({
            "symbol": ref["symbol"],
            "sector": ref["sector"],
            "rows": len(frame),
            "start": manifest["start_timestamp"],
            "end": manifest["end_timestamp"],
            "hash_matches_manifest": current_hash == manifest["dataset_hash_full"],
            "quality_status": quality["status"],
            "issue_count": quality["issue_count"],
            "issues": quality["issues"][:8],
        })
    summary = {
        "validated_at": _now(),
        "dataset_count": len(reports),
        "error_count": sum(1 for item in reports if item["quality_status"] == "error" or not item["hash_matches_manifest"]),
        "warning_count": sum(1 for item in reports if item["quality_status"] == "warning"),
        "reports": reports,
    }
    _write_json(REPORT_DIR / "quality_summary.json", summary)
    return summary


def register_collection() -> dict[str, Any]:
    collection = load_collection()
    registry = ExperimentRegistry()
    registered = []
    for ref in collection["datasets"]:
        _, manifest, quality, _ = load_dataset(ref["symbol"])
        registry.register_dataset(type("Manifest", (), {"as_dict": lambda self, data=manifest: data})(), type("Quality", (), {"as_dict": lambda self, data=quality: data})())
        registered.append({"symbol": ref["symbol"], "dataset_id": ref["dataset_id"], "dataset_hash": ref["dataset_hash"]})
    registry.close()
    result = {"registered_at": _now(), "registered_count": len(registered), "datasets": registered}
    _write_json(REPORT_DIR / "registration_summary.json", result)
    return result


def build_segmentation(*, horizons: tuple[int, ...] = (24, 75, 120), stride: int = 120) -> dict[str, Any]:
    collection = load_collection()
    rows = []
    by_split = {"development": 0, "validation": 0, "locked_test": 0}
    by_horizon: dict[str, int] = {}
    by_regime: dict[str, int] = {}
    from .regimes import tag_regime

    for ref in collection["datasets"]:
        frame, manifest, quality, _ = load_dataset(ref["symbol"])
        if quality["status"] == "error":
            continue
        for horizon in horizons:
            windows = generate_windows(
                frame,
                symbol=ref["symbol"],
                lookback_bars=400,
                horizon_bars=horizon,
                stride_bars=stride,
                session_policy="cross_session_allowed",
                max_windows=0,
            )
            total = len(windows)
            for index, window in enumerate(windows):
                if total < 3:
                    split = "development"
                elif index >= int(total * 0.8):
                    split = "locked_test"
                elif index >= int(total * 0.6):
                    split = "validation"
                else:
                    split = "development"
                context, _ = split_window(frame, window)
                regime = tag_regime(context)
                row = {
                    "symbol": ref["symbol"],
                    "sector": ref["sector"],
                    "dataset_id": manifest["dataset_id"],
                    "dataset_hash": manifest["dataset_hash_full"],
                    "horizon": horizon,
                    "stride": stride,
                    "split": split,
                    "window": asdict(window),
                    "regime": regime,
                    "overlap": overlap_summary(horizon, stride),
                }
                rows.append(row)
                by_split[split] += 1
                by_horizon[str(horizon)] = by_horizon.get(str(horizon), 0) + 1
                regime_key = f"{regime.get('trend')}|{regime.get('volatility')}|{regime.get('open_close_zone')}"
                by_regime[regime_key] = by_regime.get(regime_key, 0) + 1
    segmentation = {
        "created_at": _now(),
        "schema_version": "phase1b_segmentation_v1",
        "horizons": list(horizons),
        "stride": stride,
        "lookback_bars": 400,
        "split_policy": "first 60% development, next 20% validation, final 20% locked_test by symbol/horizon chronology",
        "locked_access_policy": "locked_test windows require an explicit unlock token",
        "counts": {"total": len(rows), "by_split": by_split, "by_horizon": by_horizon, "by_regime": by_regime},
        "windows": rows,
    }
    _write_json(SPLIT_PATH, segmentation)
    return segmentation


def lock_collection(token: str) -> dict[str, Any]:
    if not SPLIT_PATH.exists():
        build_segmentation()
    segmentation = _read_json(SPLIT_PATH)
    locked_windows = [row for row in segmentation["windows"] if row["split"] == "locked_test"]
    payload = {
        "locked_at": _now(),
        "schema_version": "phase1b_locked_subset_v1",
        "unlock_token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "locked_window_count": len(locked_windows),
        "locked_symbols": sorted({row["symbol"] for row in locked_windows}),
        "locked_horizons": sorted({row["horizon"] for row in locked_windows}),
        "policy": "Do not use locked_test in development. CLI access requires matching --unlock-token.",
    }
    _write_json(LOCK_PATH, payload)
    return {key: value for key, value in payload.items() if key != "unlock_token_hash"}


def _check_unlock(split: str, token: str | None) -> None:
    if split != "locked_test":
        return
    if not LOCK_PATH.exists():
        raise RuntimeError("Locked subset has not been locked yet. Run lock-data first.")
    lock = _read_json(LOCK_PATH)
    if not token or hashlib.sha256(token.encode("utf-8")).hexdigest() != lock["unlock_token_hash"]:
        raise PermissionError("locked_test access requires a valid --unlock-token.")


def inspect_collection() -> dict[str, Any]:
    collection = load_collection()
    quality = _read_json(REPORT_DIR / "quality_summary.json") if (REPORT_DIR / "quality_summary.json").exists() else None
    segmentation = _read_json(SPLIT_PATH) if SPLIT_PATH.exists() else None
    lock = _read_json(LOCK_PATH) if LOCK_PATH.exists() else None
    if lock:
        lock = {key: value for key, value in lock.items() if key != "unlock_token_hash"}
    return {"collection": collection, "quality": quality, "segmentation": segmentation, "lock": lock}


def run_real_pilot(
    *,
    split: str = "validation",
    adapter_name: str = "kronos",
    run_id: str | None = None,
    max_symbols: int = 1,
    max_windows: int = 1,
    horizons: tuple[int, ...] = (24,),
    unlock_token: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    _check_unlock(split, unlock_token)
    if not SPLIT_PATH.exists():
        build_segmentation()
    segmentation = _read_json(SPLIT_PATH)
    run_id = run_id or f"phase1b_real_pilot_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
    selected_symbols: set[str] = set()
    candidates = []
    for row in segmentation["windows"]:
        if row["split"] != split or int(row["horizon"]) not in horizons:
            continue
        if row["symbol"] not in selected_symbols and len(selected_symbols) >= max_symbols:
            continue
        selected_symbols.add(row["symbol"])
        candidates.append(row)
        if len(candidates) >= max_windows:
            break
    if not candidates:
        raise RuntimeError(f"No usable {split} windows matched horizons={horizons}.")
    registry = ExperimentRegistry()
    run_manifest = {
        "run_id": run_id,
        "phase": "1B",
        "split": split,
        "adapter": adapter_name,
        "selected_windows": len(candidates),
        "selected_symbols": sorted({row["symbol"] for row in candidates}),
        "horizons": list(horizons),
        "environment": environment_info(),
        "model_provenance": model_provenance(),
        "git": git_info(),
        "metrics_version": METRICS_VERSION,
        "regime_version": REGIME_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
    }
    registry.record_run(run_id, run_manifest, "running")
    executed = 0
    kronos_adapter = KronosForecastAdapter() if adapter_name == "kronos" else FakeForecastAdapter()
    settings = {"temperature": 1.0, "top_k": 0, "top_p": 0.9, "sample_count": 1}
    for row in candidates:
        frame, manifest_dict, _, _ = load_dataset(row["symbol"])
        manifest = type("Manifest", (), {"as_dict": lambda self, data=manifest_dict: data, **manifest_dict})()
        # Rehydrate the dataclass-like fields used by the runner.
        for key, value in manifest_dict.items():
            setattr(manifest, key, value)
        from .windows import BenchmarkWindow

        window = BenchmarkWindow(**row["window"])
        for baseline_name, fn in BASELINES.items():
            executed += int(run_model_experiment(
                registry=registry,
                run_id=run_id,
                model_name=baseline_name,
                adapter=BaselineAdapter(baseline_name, fn),
                bars=frame,
                manifest=manifest,
                window=window,
                settings=settings,
                system_configuration_id="kronos_only_v1",
                purpose=f"phase1b_{split}",
                force=force,
                adapter_name=adapter_name,
            ))
        executed += int(run_model_experiment(
            registry=registry,
            run_id=run_id,
            model_name="kronos" if adapter_name == "kronos" else kronos_adapter.model_name,
            adapter=kronos_adapter,
            bars=frame,
            manifest=manifest,
            window=window,
            settings=settings,
            system_configuration_id="kronos_only_v1",
            purpose=f"phase1b_{split}",
            force=force,
            adapter_name=adapter_name,
        ))
    registry.finish_run(run_id, "completed_with_errors" if registry.summary(run_id)["failed_count"] else "completed")
    report_path = generate_markdown_report(run_id, registry)
    summary = registry.summary(run_id)
    registry.close()
    return {"run_id": run_id, "executed_or_reused": executed, "summary": summary, "report_path": str(report_path)}


def readiness_report(pilot_run_id: str | None = None) -> Path:
    inspection = inspect_collection()
    quality = inspection.get("quality") or {}
    segmentation = inspection.get("segmentation") or {}
    collection = inspection["collection"]
    path = REPORT_DIR / "phase1b_readiness_report.md"
    lines = [
        "# Kronos Copilot Phase 1B Readiness Report",
        "",
        f"Generated: {_now()}",
        "",
        "## Dataset Universe",
        f"- Symbols acquired: {collection.get('symbols_acquired')} / {collection.get('symbols_requested')}",
        f"- Provider: {collection.get('provider')} ({collection.get('provider_version')})",
        f"- Interval: {collection.get('interval')}",
        "",
        "## Symbols And Sectors",
    ]
    for ref in collection.get("datasets", []):
        lines.append(f"- {ref['symbol']} — {ref['sector']} — rows {ref['rows']} — {ref['start']} to {ref['end']} — quality {ref['quality_status']}")
    lines.extend([
        "",
        "## Quality Summary",
        f"- Errors: {quality.get('error_count')}",
        f"- Warnings: {quality.get('warning_count')}",
        "- Session gaps are reported separately from unknown calendar/holiday gaps; missing bars are never filled.",
        "",
        "## Segmentation",
        "```json",
        json.dumps(segmentation.get("counts", {}), indent=2),
        "```",
        "",
        "## Locked Test Design",
        "- Locked windows are the final chronological 20% per symbol/horizon.",
        "- Access requires `--unlock-token`; development and validation runs do not consume locked_test.",
        "",
        "## Pilot Benchmark",
        f"- Pilot run ID: {pilot_run_id or 'not run'}",
        "- Pilot execution is intentionally tiny and must not be read as final model quality.",
        "",
        "## Runtime Estimate",
        "- Full benchmark calls roughly equal usable windows multiplied by selected model configurations.",
        f"- Current usable windows: {segmentation.get('counts', {}).get('total', 0)}",
        "",
        "## Remaining Scientific Limitations",
        "- Yahoo/yfinance recent intraday data is provider-limited and may be revised or delayed.",
        "- Phase 1B does not yet include a full exchange holiday calendar.",
        "- No OpenBB, news, fundamentals, macro, indicators, or alternative models are included.",
        "- Large Kronos benchmark should wait until this pilot report is reviewed.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
