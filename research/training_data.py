"""Phase 1E research-only training data feasibility helpers.

This module prepares raw/normalized intraday data for future training phases.
It does not create Kronos training samples, run inference, or touch the product.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import DATASET_DIR
from .datasets import DataQualityError, QualityIssue, QualityReport, canonicalize_bars, dataset_hash, quality_report
from .real_market import SPLIT_PATH, load_collection

TRAINING_ROOT = DATASET_DIR / "training"
TRAINING_RAW_DIR = TRAINING_ROOT / "raw"
TRAINING_NORMALIZED_DIR = TRAINING_ROOT / "normalized"
TRAINING_MANIFEST_DIR = TRAINING_ROOT / "manifests"
TRAINING_QUALITY_DIR = TRAINING_ROOT / "quality"
TRAINING_PROOF_DIR = TRAINING_ROOT / "proof"

RAW_SCHEMA_VERSION = "phase1e_raw_intraday_v1"
TRAINING_MANIFEST_VERSION = "phase1e_training_manifest_v1"
TRAINING_QUALITY_VERSION = "phase1e_training_quality_v1"
PROTECTED_SPLITS = ("development", "validation", "locked_test")
INDIA_TZ = "Asia/Kolkata"
REQUIRED_RAW_COLUMNS = ("symbol", "exchange", "timestamp", "open", "high", "low", "close", "volume")
METADATA_COLUMNS = ("source", "source_symbol", "timezone", "currency", "interval", "downloaded_at")
OPTIONAL_TRAINING_COLUMNS = ("amount",)
SESSION_START = (9, 15)
SESSION_END = (15, 25)


@dataclass(frozen=True)
class TrainingDatasetManifest:
    dataset_id: str
    dataset_hash_full: str
    dataset_hash_algorithm: str
    schema_version: str
    manifest_version: str
    source: str
    source_symbol: str
    symbol: str
    exchange: str
    interval: str
    timezone: str
    currency: str | None
    downloaded_at: str
    registered_at: str
    start_timestamp: str
    end_timestamp: str
    row_count: int
    columns: tuple[str, ...]
    quality_status: str
    quality_report_id: str
    safety_status: str
    lineage: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def ensure_training_dirs() -> None:
    for path in (TRAINING_RAW_DIR, TRAINING_NORMALIZED_DIR, TRAINING_MANIFEST_DIR, TRAINING_QUALITY_DIR, TRAINING_PROOF_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    return pd.Timestamp.now(tz=timezone.utc).isoformat()


def normalize_raw_intraday(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    source: str,
    source_symbol: str | None = None,
    interval: str = "5m",
    timezone_name: str = INDIA_TZ,
    currency: str | None = "INR",
    downloaded_at: str | None = None,
) -> pd.DataFrame:
    """Normalize provider-shaped intraday data into the Phase 1E raw schema."""

    data = frame.copy()
    rename_map = {
        "datetime": "timestamp",
        "date": "timestamp",
        "time": "timestamp",
        "timestamps": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "vol": "volume",
    }
    data = data.rename(columns={key: value for key, value in rename_map.items() if key in data.columns})
    core = canonicalize_bars(data)
    core = core.sort_values("timestamp").reset_index(drop=True)
    core.insert(0, "exchange", exchange.upper())
    core.insert(0, "symbol", symbol.upper())
    stamp = downloaded_at or now_utc_iso()
    core["source"] = source
    core["source_symbol"] = source_symbol or symbol
    core["timezone"] = timezone_name
    core["currency"] = currency
    core["interval"] = interval
    core["downloaded_at"] = stamp
    optional_columns = [column for column in OPTIONAL_TRAINING_COLUMNS if column in core.columns]
    return core[[*REQUIRED_RAW_COLUMNS, *optional_columns, *METADATA_COLUMNS]]


def training_hash(frame: pd.DataFrame) -> str:
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"]).map(lambda value: pd.Timestamp(value).isoformat())
    stable = data.sort_values(["symbol", "exchange", "timestamp"]).to_csv(index=False, float_format="%.8f")
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _quality_dict(report: QualityReport) -> dict[str, Any]:
    return report.as_dict()


def validate_training_dataset(frame: pd.DataFrame, *, interval_minutes: int = 5) -> dict[str, Any]:
    missing = [column for column in REQUIRED_RAW_COLUMNS if column not in frame.columns]
    if missing:
        issue = QualityIssue("MISSING_TRAINING_COLUMN", "error", len(missing), tuple(missing), "Training data is missing required raw-schema columns.")
        report = QualityReport("quality_" + hashlib.sha256(",".join(missing).encode("utf-8")).hexdigest()[:16], False, "error", 1, (issue,), TRAINING_QUALITY_VERSION)
        return {"status": "error", "report": _quality_dict(report), "summary": {"missing_columns": missing}}

    data = frame.copy()
    per_symbol_reports = []
    aggregate_issues = []
    for (symbol, exchange), group in data.groupby(["symbol", "exchange"], sort=False):
        report = quality_report(group.sort_values("timestamp"))
        per_symbol_reports.append({"symbol": symbol, "exchange": exchange, "report": report.as_dict()})
        aggregate_issues.extend(report.issues)
    timestamps = pd.to_datetime(data["timestamp"], errors="coerce")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(INDIA_TZ)
    else:
        timestamps = timestamps.dt.tz_convert(INDIA_TZ)
    expected_delta = pd.to_timedelta(int(interval_minutes), unit="min")
    duplicate_keys = data.duplicated(subset=["symbol", "exchange", "timestamp"]).sum()
    gap_count = 0
    for _, group in data.assign(_ts=timestamps).groupby(["symbol", "exchange"], sort=False):
        deltas = group["_ts"].sort_values().diff().dropna()
        gap_count += int((deltas[(deltas > expected_delta)]).count())

    has_error = duplicate_keys or any(issue.severity == "error" for issue in aggregate_issues)
    has_warning = gap_count or any(issue.severity == "warning" for issue in aggregate_issues)
    status = "error" if has_error else "warning" if has_warning else "valid"
    digest = hashlib.sha256(json.dumps(per_symbol_reports, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "status": status,
        "report": {
            "report_id": f"phase1e_quality_{digest[:16]}",
            "status": status,
            "valid": status != "error",
            "issue_count": len(aggregate_issues) + int(duplicate_keys > 0),
            "schema_version": TRAINING_QUALITY_VERSION,
            "per_symbol_reports": per_symbol_reports,
        },
        "summary": {
            "row_count": int(len(data)),
            "symbol_count": int(data["symbol"].nunique()),
            "duplicate_symbol_timestamp_rows": int(duplicate_keys),
            "gap_count": int(gap_count),
            "start_timestamp": timestamps.min().isoformat() if len(timestamps) else None,
            "end_timestamp": timestamps.max().isoformat() if len(timestamps) else None,
            "interval_minutes": interval_minutes,
            "timezone": INDIA_TZ,
        },
    }


def protected_evaluation_boundaries() -> dict[str, Any]:
    """Read only protected metadata from Phase 1B segmentation."""

    segmentation = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    boundaries: dict[str, Any] = {"source": str(SPLIT_PATH), "splits": {}, "by_symbol": {}}
    for split in PROTECTED_SPLITS:
        split_rows = [row for row in segmentation["windows"] if row["split"] == split]
        timestamps: list[str] = []
        for row in split_rows:
            window = row["window"]
            timestamps.extend([window["context_start"], window["context_end"], window["future_start"], window["future_end"]])
            symbol = row["symbol"]
            symbol_key = f"{symbol}|{split}"
            symbol_times = boundaries["by_symbol"].setdefault(symbol_key, {"symbol": symbol, "split": split, "timestamps": []})
            symbol_times["timestamps"].extend([window["context_start"], window["context_end"], window["future_start"], window["future_end"]])
        boundaries["splits"][split] = {
            "window_count": len(split_rows),
            "start": min(timestamps) if timestamps else None,
            "end": max(timestamps) if timestamps else None,
        }
    for value in boundaries["by_symbol"].values():
        times = value.pop("timestamps")
        value["start"] = min(times) if times else None
        value["end"] = max(times) if times else None
    starts = [value["start"] for value in boundaries["splits"].values() if value["start"]]
    boundaries["global_training_must_end_before"] = min(starts) if starts else None
    return boundaries


def _is_market_bar(timestamp: pd.Timestamp) -> bool:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize(INDIA_TZ)
    else:
        ts = ts.tz_convert(INDIA_TZ)
    minutes = ts.hour * 60 + ts.minute
    start = SESSION_START[0] * 60 + SESSION_START[1]
    end = SESSION_END[0] * 60 + SESSION_END[1]
    return ts.weekday() < 5 and start <= minutes <= end and minutes % 5 == 0


def previous_market_bar(timestamp: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize(INDIA_TZ)
    else:
        ts = ts.tz_convert(INDIA_TZ)
    ts -= pd.to_timedelta(5, unit="min")
    while not _is_market_bar(ts):
        ts -= pd.to_timedelta(5, unit="min")
    return ts


def subtract_market_bars(timestamp: pd.Timestamp, bars: int) -> pd.Timestamp:
    ts = pd.Timestamp(timestamp)
    for _ in range(int(bars)):
        ts = previous_market_bar(ts)
    return ts


def training_cutoff_spec(*, lookback_bars: int = 400, max_horizon_bars: int = 120, extra_embargo_bars: int = 0) -> dict[str, Any]:
    protected = protected_evaluation_boundaries()
    first_protected = pd.Timestamp(protected["global_training_must_end_before"])
    no_embargo_latest = previous_market_bar(first_protected)
    embargo_bars = int(lookback_bars) + int(max_horizon_bars) + int(extra_embargo_bars)
    latest_allowed = subtract_market_bars(first_protected, embargo_bars)
    return {
        "schema_version": "phase1e_training_cutoff_v1",
        "source": protected["source"],
        "first_protected_timestamp": first_protected.isoformat(),
        "latest_allowed_without_embargo": no_embargo_latest.isoformat(),
        "lookback_bars": int(lookback_bars),
        "max_horizon_bars": int(max_horizon_bars),
        "extra_embargo_bars": int(extra_embargo_bars),
        "embargo_bars": embargo_bars,
        "latest_allowed_training_timestamp": latest_allowed.isoformat(),
        "interval": "5m",
        "timezone": INDIA_TZ,
        "holiday_limitation": "Weekends and regular sessions are handled; exchange holidays require a calendar-aware source in Phase 1E-C/D.",
        "policy": "Every raw training timestamp and every generated training target must be at or before latest_allowed_training_timestamp.",
    }


def assert_phase1e_training_cutoff(frame: pd.DataFrame, *, cutoff: dict[str, Any] | None = None) -> dict[str, Any]:
    cutoff = cutoff or training_cutoff_spec()
    data = frame.copy()
    timestamps = pd.to_datetime(data["timestamp"], errors="coerce")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(INDIA_TZ)
    else:
        timestamps = timestamps.dt.tz_convert(INDIA_TZ)
    latest = pd.Timestamp(cutoff["latest_allowed_training_timestamp"])
    if len(timestamps) and timestamps.max() > latest:
        return {
            "safe": False,
            "status": "fail",
            "issue_count": 1,
            "issues": [{
                "code": "PHASE1E_EMBARGO_VIOLATION",
                "severity": "error",
                "dataset_end": timestamps.max().isoformat(),
                "latest_allowed_training_timestamp": latest.isoformat(),
            }],
            "cutoff": cutoff,
        }
    return {"safe": True, "status": "pass", "issue_count": 0, "issues": [], "cutoff": cutoff}


def assert_training_dataset_safe(frame: pd.DataFrame, *, protected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fail future training registration if raw data overlaps protected evaluation periods."""

    protected = protected or protected_evaluation_boundaries()
    data = frame.copy()
    timestamps = pd.to_datetime(data["timestamp"], errors="coerce")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(INDIA_TZ)
    else:
        timestamps = timestamps.dt.tz_convert(INDIA_TZ)
    issues: list[dict[str, Any]] = []
    global_cutoff = protected.get("global_training_must_end_before")
    if global_cutoff and len(timestamps):
        cutoff = pd.Timestamp(global_cutoff)
        if timestamps.max() >= cutoff:
            issues.append({
                "code": "TRAINING_AFTER_PROTECTED_START",
                "severity": "error",
                "message": "Training data reaches or follows the earliest protected evaluation timestamp.",
                "dataset_end": timestamps.max().isoformat(),
                "must_end_before": cutoff.isoformat(),
            })
    for row in data.assign(ts_for_guard=timestamps).itertuples(index=False):
        symbol = getattr(row, "symbol")
        ts = getattr(row, "ts_for_guard")
        for split in PROTECTED_SPLITS:
            boundary = protected["by_symbol"].get(f"{symbol}|{split}")
            if not boundary:
                continue
            start = pd.Timestamp(boundary["start"])
            end = pd.Timestamp(boundary["end"])
            if start <= ts <= end:
                issues.append({
                    "code": "PROTECTED_TIMESTAMP_OVERLAP",
                    "severity": "error",
                    "symbol": symbol,
                    "split": split,
                    "timestamp": ts.isoformat(),
                    "protected_start": start.isoformat(),
                    "protected_end": end.isoformat(),
                })
                break
    return {"safe": not issues, "status": "pass" if not issues else "fail", "issue_count": len(issues), "issues": issues[:20], "policy": "training data must end before the earliest Phase 1B development/validation/locked-test timestamp and must not contain protected symbol timestamps"}


def to_kronos_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the CSV shape expected by official Kronos finetune_csv."""

    data = frame.copy()
    if "amount" not in data.columns:
        data["amount"] = pd.to_numeric(data["close"], errors="coerce") * pd.to_numeric(data["volume"], errors="coerce").fillna(0)
    out = data.rename(columns={"timestamp": "timestamps"})
    out["timestamps"] = pd.to_datetime(out["timestamps"]).map(lambda value: pd.Timestamp(value).isoformat())
    return out[["timestamps", "open", "high", "low", "close", "volume", "amount"]].copy()


def _valid_sequence_timestamps(timestamps: pd.Series) -> tuple[bool, str | None]:
    times = pd.to_datetime(timestamps)
    if times.dt.tz is None:
        times = times.dt.tz_localize(INDIA_TZ)
    else:
        times = times.dt.tz_convert(INDIA_TZ)
    if not times.is_monotonic_increasing:
        return False, "timestamps_not_ordered"
    for ts in times:
        if not _is_market_bar(pd.Timestamp(ts)):
            return False, "outside_market_session"
    for previous, current in zip(times.iloc[:-1], times.iloc[1:]):
        delta = current - previous
        if previous.date() == current.date():
            if delta != pd.to_timedelta(5, unit="min"):
                return False, "missing_intraday_bar"
        else:
            if previous.hour != SESSION_END[0] or previous.minute != SESSION_END[1]:
                return False, "unexpected_cross_session_start"
            if current.hour != SESSION_START[0] or current.minute != SESSION_START[1]:
                return False, "unexpected_cross_session_resume"
            if current.weekday() >= 5:
                return False, "weekend_resume"
    return True, None


def generate_kronos_training_windows(
    frame: pd.DataFrame,
    *,
    lookback_window: int = 512,
    predict_window: int = 75,
    stride_bars: int = 75,
    seed: int = 20260831,
    cutoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate deterministic Kronos-compatible sequence metadata without training."""

    data = frame.copy().sort_values(["symbol", "exchange", "timestamp"]).reset_index(drop=True)
    safety = assert_training_dataset_safe(data)
    embargo = assert_phase1e_training_cutoff(data, cutoff=cutoff)
    quality = validate_training_dataset(data)
    if not safety["safe"] or not embargo["safe"] or quality["status"] == "error":
        return {
            "schema_version": "phase1e_kronos_window_manifest_v1",
            "status": "blocked",
            "window_count": 0,
            "rejected_sequence_count": 0,
            "rejection_reasons": {"dataset_safety_or_quality_gate_failed": 1},
            "safety": safety,
            "embargo": embargo,
            "quality": quality,
        }
    rows = []
    rejected: dict[str, int] = {}
    dataset_digest = training_hash(data)
    sequence_len = int(lookback_window) + int(predict_window) + 1
    for (symbol, exchange), group in data.groupby(["symbol", "exchange"], sort=False):
        group = group.sort_values("timestamp").reset_index(drop=True)
        max_start = len(group) - sequence_len
        if max_start < 0:
            rejected["insufficient_rows"] = rejected.get("insufficient_rows", 0) + 1
            continue
        for start in range(0, max_start + 1, int(stride_bars)):
            end = start + sequence_len
            window = group.iloc[start:end]
            ok, reason = _valid_sequence_timestamps(window["timestamp"])
            if not ok:
                rejected[reason or "invalid_sequence"] = rejected.get(reason or "invalid_sequence", 0) + 1
                continue
            payload = {
                "dataset_hash": dataset_digest,
                "symbol": symbol,
                "exchange": exchange,
                "lookback_window": int(lookback_window),
                "predict_window": int(predict_window),
                "start_timestamp": pd.Timestamp(window["timestamp"].iloc[0]).isoformat(),
                "context_end_timestamp": pd.Timestamp(window["timestamp"].iloc[int(lookback_window) - 1]).isoformat(),
                "target_start_timestamp": pd.Timestamp(window["timestamp"].iloc[int(lookback_window)]).isoformat(),
                "target_end_timestamp": pd.Timestamp(window["timestamp"].iloc[-1]).isoformat(),
                "seed": int(seed),
            }
            rows.append({"sequence_id": hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24], **payload})
    return {
        "schema_version": "phase1e_kronos_window_manifest_v1",
        "status": "pass",
        "window_count": len(rows),
        "rejected_sequence_count": sum(rejected.values()),
        "rejection_reasons": rejected,
        "lookback_window": int(lookback_window),
        "predict_window": int(predict_window),
        "sequence_length": sequence_len,
        "stride_bars": int(stride_bars),
        "seed": int(seed),
        "dataset_hash": dataset_digest,
        "symbols": sorted(data["symbol"].unique()),
        "windows": rows,
        "safety": safety,
        "embargo": embargo,
        "quality": quality,
    }


def build_training_manifest(frame: pd.DataFrame, *, source: str, source_symbol: str, notes: str = "", safety: dict[str, Any] | None = None) -> TrainingDatasetManifest:
    data = frame.copy()
    quality = validate_training_dataset(data)
    digest = training_hash(data)
    timestamps = pd.to_datetime(data["timestamp"]).dt.tz_convert(INDIA_TZ)
    symbols = sorted(data["symbol"].unique())
    exchanges = sorted(data["exchange"].unique())
    return TrainingDatasetManifest(
        dataset_id=f"phase1e_{source_symbol}_{digest[:16]}",
        dataset_hash_full=digest,
        dataset_hash_algorithm="sha256",
        schema_version=RAW_SCHEMA_VERSION,
        manifest_version=TRAINING_MANIFEST_VERSION,
        source=source,
        source_symbol=source_symbol,
        symbol=",".join(symbols),
        exchange=",".join(exchanges),
        interval=str(data["interval"].iloc[0]),
        timezone=str(data["timezone"].iloc[0]),
        currency=str(data["currency"].iloc[0]) if "currency" in data.columns else None,
        downloaded_at=str(data["downloaded_at"].iloc[0]),
        registered_at=now_utc_iso(),
        start_timestamp=timestamps.min().isoformat(),
        end_timestamp=timestamps.max().isoformat(),
        row_count=len(data),
        columns=tuple(data.columns),
        quality_status=quality["status"],
        quality_report_id=str(quality["report"]["report_id"]),
        safety_status=(safety or {}).get("status", "unchecked"),
        lineage={"stage": "phase1e-proof", "raw_dataset_id": source_symbol},
        notes=notes,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def propose_training_universe(limit: int = 120) -> dict[str, Any]:
    cache_path = Path("data/instrument_master_cache.json")
    if not cache_path.exists():
        collection = load_collection()
        instruments = [{"symbol": item["symbol"].replace(".NS", ""), "yahoo_symbol": item["symbol"], "company_name": item["name"], "exchange": "NSE", "source": "phase1b_pilot"} for item in collection["datasets"]]
    else:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        instruments = cache.get("instruments", [])
    nse_equities = [item for item in instruments if item.get("exchange") == "NSE" and item.get("instrument_type") == "EQUITY"]
    selected = nse_equities[:limit]
    return {
        "schema_version": "phase1e_training_universe_v1",
        "selection_policy": "First pass uses existing local NSE equity instrument master as the candidate pool; Phase 1E-C must refine by liquidity, completeness, sector labels, and history availability before training.",
        "target_size": limit,
        "selected_count": len(selected),
        "candidate_pool_count": len(nse_equities),
        "symbols": selected,
    }


def build_saved_yahoo_proof(symbols: tuple[str, ...] = ("RELIANCE.NS", "TCS.NS", "INFY.NS"), rows_per_symbol: int = 150) -> dict[str, Any]:
    """Create a no-network proof artifact from already saved Phase 1B Yahoo bars."""

    from .real_market import PHASE1B_ROOT

    ensure_training_dirs()
    normalized_frames = []
    for symbol in symbols:
        path = PHASE1B_ROOT / "raw" / f"{symbol.replace('.', '_')}.csv.gz"
        raw = pd.read_csv(path, compression="gzip").head(rows_per_symbol)
        normalized_frames.append(normalize_raw_intraday(raw, symbol=symbol, exchange="NSE", source="saved_yfinance_phase1b", source_symbol=symbol, downloaded_at="preserved-from-phase1b"))
    combined = pd.concat(normalized_frames, ignore_index=True)
    quality = validate_training_dataset(combined)
    safety = assert_training_dataset_safe(combined)
    manifest = build_training_manifest(combined, source="saved_yfinance_phase1b", source_symbol="phase1e_saved_yahoo_3symbol_proof", notes="No new Yahoo request. Existing saved Phase 1B bars used only to test schema/quality/safety plumbing; not approved for training.", safety=safety)
    data_path = TRAINING_PROOF_DIR / "phase1e_saved_yahoo_3symbol_proof.csv.gz"
    combined.to_csv(data_path, index=False, compression="gzip")
    write_json(TRAINING_MANIFEST_DIR / "phase1e_saved_yahoo_3symbol_proof_manifest.json", manifest.as_dict())
    write_json(TRAINING_QUALITY_DIR / "phase1e_saved_yahoo_3symbol_proof_quality.json", quality)
    write_json(TRAINING_QUALITY_DIR / "phase1e_saved_yahoo_3symbol_proof_safety.json", safety)
    return {
        "data_path": str(data_path),
        "manifest": manifest.as_dict(),
        "quality": quality,
        "safety": safety,
        "network_requests": 0,
        "registered_for_training": False,
    }



def parse_nse_fno_1m_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str = "NSE",
    source: str = "voletiramu_nse_fno_1min_data",
    source_symbol: str | None = None,
    downloaded_at: str | None = None,
) -> pd.DataFrame:
    """Normalize the audited GitHub 1-minute source shape without registering it."""

    data = frame.copy()
    rename_map = {
        "time": "timestamp",
        "datetime": "timestamp",
        "date": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "vol": "volume",
        "Amount": "amount",
        "Turnover": "amount",
    }
    data = data.rename(columns={key: value for key, value in rename_map.items() if key in data.columns})
    if "timestamp" not in data.columns:
        raise DataQualityError("1-minute source data is missing a time/timestamp column")
    if pd.api.types.is_numeric_dtype(data["timestamp"]):
        timestamps = pd.to_datetime(data["timestamp"], unit="s", utc=True, errors="coerce").dt.tz_convert(INDIA_TZ)
    else:
        timestamps = pd.to_datetime(data["timestamp"], errors="coerce")
        if timestamps.dt.tz is None:
            timestamps = timestamps.dt.tz_localize(INDIA_TZ)
        else:
            timestamps = timestamps.dt.tz_convert(INDIA_TZ)
    data["timestamp"] = timestamps
    missing = [column for column in ("open", "high", "low", "close", "volume") if column not in data.columns]
    if missing:
        raise DataQualityError(f"1-minute source data is missing required columns: {', '.join(missing)}")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    if "amount" not in data.columns:
        data["amount"] = data["close"] * data["volume"]
    stamp = downloaded_at or now_utc_iso()
    data["symbol"] = symbol.upper()
    data["exchange"] = exchange.upper()
    data["source"] = source
    data["source_symbol"] = source_symbol or symbol.upper()
    data["timezone"] = INDIA_TZ
    data["currency"] = "INR"
    data["interval"] = "1m"
    data["downloaded_at"] = stamp
    return data[["symbol", "exchange", "timestamp", "open", "high", "low", "close", "volume", "amount", *METADATA_COLUMNS]].sort_values("timestamp").reset_index(drop=True)


def _is_one_minute_market_bar(timestamp: pd.Timestamp) -> bool:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize(INDIA_TZ)
    else:
        ts = ts.tz_convert(INDIA_TZ)
    minutes = ts.hour * 60 + ts.minute
    start = SESSION_START[0] * 60 + SESSION_START[1]
    end = 15 * 60 + 29
    return ts.weekday() < 5 and start <= minutes <= end


def resample_1m_to_5m(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str = "NSE",
    source: str = "voletiramu_nse_fno_1min_data",
    source_symbol: str | None = None,
    downloaded_at: str | None = None,
    allow_partial: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Deterministically aggregate 1-minute NSE session bars into 5-minute bars."""

    one_minute = parse_nse_fno_1m_frame(
        frame,
        symbol=symbol,
        exchange=exchange,
        source=source,
        source_symbol=source_symbol,
        downloaded_at=downloaded_at,
    )
    rows: list[dict[str, Any]] = []
    partial_counts = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0, "0": 0}
    rejected_reasons: dict[str, int] = {}
    valid_source = one_minute[one_minute["timestamp"].map(lambda ts: _is_one_minute_market_bar(pd.Timestamp(ts)))].copy()
    outside_session = len(one_minute) - len(valid_source)
    if outside_session:
        rejected_reasons["outside_session_1m_rows"] = int(outside_session)
    if valid_source.empty:
        report = {
            "schema_version": "phase1e_c2_resample_report_v1",
            "status": "fail",
            "raw_1m_rows": int(len(one_minute)),
            "accepted_5m_rows": 0,
            "partial_bar_policy": "5/5 pass; 4/5 warn but rejected unless allow_partial=True; 1-3/5 fail; interpolation forbidden",
            "partial_5m_counts": partial_counts,
            "rejected_reasons": rejected_reasons or {"no_session_rows": 1},
            "amount_policy": "source amount summed when present; otherwise close*volume proxy after aggregation",
        }
        return normalize_raw_intraday(pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "amount"]), symbol=symbol, exchange=exchange, source=source), report

    valid_source["session_date"] = pd.to_datetime(valid_source["timestamp"]).dt.date
    start_minutes = SESSION_START[0] * 60 + SESSION_START[1]
    valid_source["bucket"] = valid_source["timestamp"].map(lambda ts: (pd.Timestamp(ts).hour * 60 + pd.Timestamp(ts).minute - start_minutes) // 5)
    for (_, bucket), group in valid_source.groupby(["session_date", "bucket"], sort=True):
        group = group.sort_values("timestamp")
        count = int(len(group))
        partial_counts[str(min(count, 5))] = partial_counts.get(str(min(count, 5)), 0) + 1
        if count < 5 and not allow_partial:
            rejected_reasons[f"partial_{count}_of_5"] = rejected_reasons.get(f"partial_{count}_of_5", 0) + 1
            continue
        if count < 4:
            rejected_reasons[f"too_sparse_{count}_of_5"] = rejected_reasons.get(f"too_sparse_{count}_of_5", 0) + 1
            continue
        timestamp = pd.Timestamp(group["timestamp"].iloc[0])
        rows.append({
            "timestamp": timestamp,
            "open": float(group["open"].iloc[0]),
            "high": float(group["high"].max()),
            "low": float(group["low"].min()),
            "close": float(group["close"].iloc[-1]),
            "volume": float(group["volume"].sum()),
            "amount": float(group["amount"].sum()) if "amount" in group else float(group["close"].iloc[-1] * group["volume"].sum()),
        })
    if rows:
        five_minute = pd.DataFrame(rows)
        normalized = normalize_raw_intraday(
            five_minute,
            symbol=symbol,
            exchange=exchange,
            source=source,
            source_symbol=source_symbol or symbol,
            interval="5m",
            timezone_name=INDIA_TZ,
            currency="INR",
            downloaded_at=downloaded_at,
        )
    else:
        normalized = pd.DataFrame(columns=[*REQUIRED_RAW_COLUMNS, "amount", *METADATA_COLUMNS])
    report = {
        "schema_version": "phase1e_c2_resample_report_v1",
        "status": "pass" if not rejected_reasons else "warning",
        "raw_1m_rows": int(len(one_minute)),
        "accepted_5m_rows": int(len(normalized)),
        "partial_bar_policy": "5/5 pass; 4/5 warn but rejected unless allow_partial=True; 1-3/5 fail; interpolation forbidden",
        "partial_5m_counts": partial_counts,
        "rejected_reasons": rejected_reasons,
        "amount_policy": "source amount summed when present; otherwise close*volume proxy after aggregation",
        "session_alignment": "09:15 is the first valid bucket; no bucket crosses a trading day or session boundary",
    }
    return normalized, report


def phase1e_c2_source_audit_metadata() -> dict[str, Any]:
    """Return the pinned audit decision for the selected public dataset candidate."""

    return {
        "schema_version": "phase1e_c2_source_audit_v1",
        "source": "voletiramu/nse-fno-1min-data",
        "source_url": "https://github.com/voletiramu/nse-fno-1min-data",
        "owner": "voletiramu",
        "default_branch": "main",
        "pinned_commit_sha": "2c01a18c694f245556ff58bf7b882280f1de3679",
        "release_tag": "v1.0.0",
        "release_asset": "stocks_1m_csvs.zip",
        "release_asset_size_bytes": 485923642,
        "archive_sha256": None,
        "archive_hash_status": "not_downloaded_because_data_license_is_not_sufficiently_clear",
        "repository_license": None,
        "declared_data_use": "AS-IS for research and educational use; not for redistribution as a commercial product; respect NSE/Zerodha terms",
        "source_type": "spot equity OHLCV for NSE F&O underlyings, not futures/options contracts, according to README; still third-party compiled data",
        "date_coverage_declared": "2024-04-01 to 2026-04-30",
        "interval_declared": "1m",
        "symbol_coverage_declared": "214 NSE F&O underlying stocks",
        "legal_provenance_status": "uncertain",
        "scientific_decision": "YELLOW: engineering adapter can support it, but no real training import is approved until data rights and archive hash are resolved",
    }
