"""Dataset loading, validation, manifests, and synthetic smoke data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from .config import BAR_COLUMNS, OPTIONAL_COLUMNS


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    symbol: str
    exchange: str
    interval: str
    source: str
    start_timestamp: str
    end_timestamp: str
    row_count: int
    columns: tuple[str, ...]
    sha256: str
    timezone: str
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class DataQualityError(ValueError):
    pass


def canonicalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "timestamps" in data.columns and "timestamp" not in data.columns:
        data = data.rename(columns={"timestamps": "timestamp"})
    missing = [column for column in BAR_COLUMNS if column not in data.columns]
    if missing:
        raise DataQualityError(f"Dataset is missing required columns: {', '.join(missing)}")
    data = data[[*BAR_COLUMNS, *[column for column in OPTIONAL_COLUMNS if column in data.columns]]].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
    if data["timestamp"].dt.tz is None:
        data["timestamp"] = data["timestamp"].dt.tz_localize("Asia/Kolkata")
    else:
        data["timestamp"] = data["timestamp"].dt.tz_convert("Asia/Kolkata")
    for column in ["open", "high", "low", "close", "volume", *[c for c in OPTIONAL_COLUMNS if c in data.columns]]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data


def validate_bars(frame: pd.DataFrame) -> list[str]:
    data = canonicalize_bars(frame)
    issues: list[str] = []
    if data["timestamp"].isna().any():
        issues.append("invalid timestamps")
    if data[["open", "high", "low", "close"]].isna().any().any():
        issues.append("missing or nonnumeric OHLC")
    if data["volume"].isna().any():
        issues.append("missing or nonnumeric volume")
    if data["timestamp"].duplicated().any():
        issues.append("duplicate timestamps")
    if not data["timestamp"].is_monotonic_increasing:
        issues.append("timestamps are not ordered")
    if (data[["open", "high", "low", "close"]] < 0).any().any():
        issues.append("negative OHLC price")
    if (data["volume"] < 0).any():
        issues.append("negative volume")
    impossible = (data["high"] < data[["open", "close", "low"]].max(axis=1)) | (data["low"] > data[["open", "close", "high"]].min(axis=1))
    if impossible.any():
        issues.append("impossible candle high/low relationship")
    if len(data) >= 20 and (data["volume"] == 0).mean() > 0.8:
        issues.append("suspicious zero-volume pattern")
    returns = data["close"].pct_change().abs()
    if (returns > 0.35).any():
        issues.append("extreme close discontinuity above 35%")
    return issues


def dataset_hash(frame: pd.DataFrame) -> str:
    data = canonicalize_bars(frame).copy()
    data["timestamp"] = data["timestamp"].map(lambda value: pd.Timestamp(value).isoformat())
    for column in ["open", "high", "low", "close"]:
        data[column] = pd.to_numeric(data[column], errors="coerce").round(6)
    data["volume"] = pd.to_numeric(data["volume"], errors="coerce").round(0).astype("Int64")
    for column in [c for c in OPTIONAL_COLUMNS if c in data.columns]:
        data[column] = pd.to_numeric(data[column], errors="coerce").round(2)
    stable = data.to_csv(index=False, float_format="%.6f")
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def build_manifest(frame: pd.DataFrame, *, symbol: str, exchange: str, interval: str, source: str, notes: str = "") -> DatasetManifest:
    data = canonicalize_bars(frame)
    sha = dataset_hash(data)
    return DatasetManifest(
        dataset_id=f"{symbol}_{interval}_{sha[:12]}",
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        source=source,
        start_timestamp=data["timestamp"].iloc[0].isoformat(),
        end_timestamp=data["timestamp"].iloc[-1].isoformat(),
        row_count=len(data),
        columns=tuple(data.columns),
        sha256=sha,
        timezone="Asia/Kolkata",
        notes=notes,
    )


def load_csv_dataset(path: str | Path, *, symbol: str = "CSV", exchange: str = "CSV", interval: str = "5m") -> tuple[pd.DataFrame, DatasetManifest, list[str]]:
    frame = canonicalize_bars(pd.read_csv(path))
    issues = validate_bars(frame)
    manifest = build_manifest(frame, symbol=symbol, exchange=exchange, interval=interval, source=f"csv:{Path(path).name}", notes="local CSV benchmark dataset")
    return frame, manifest, issues


def save_manifest(path: str | Path, manifest: DatasetManifest) -> None:
    Path(path).write_text(json.dumps(manifest.as_dict(), indent=2), encoding="utf-8")


def synthetic_market_data(rows: int = 620, *, symbol: str = "SYNTH") -> tuple[pd.DataFrame, DatasetManifest]:
    start = pd.Timestamp("2026-01-05 09:15", tz="Asia/Kolkata")
    timestamps = []
    day = start
    while len(timestamps) < rows:
        current = pd.Timestamp(day.date().isoformat() + " 09:15", tz="Asia/Kolkata")
        for _ in range(75):
            timestamps.append(current)
            current += timedelta(minutes=5)
            if len(timestamps) >= rows:
                break
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    closes = []
    price = 100.0
    for index in range(rows):
        price += 0.018 + ((index % 17) - 8) * 0.006
        closes.append(round(price, 4))
    data = pd.DataFrame({
        "timestamp": timestamps,
        "open": [round(value - 0.08, 4) for value in closes],
        "high": [round(value + 0.18, 4) for value in closes],
        "low": [round(value - 0.22, 4) for value in closes],
        "close": closes,
        "volume": [1000 + (index % 29) * 10 for index in range(rows)],
        "amount": [round(closes[index] * (1000 + (index % 29) * 10), 2) for index in range(rows)],
    })
    manifest = build_manifest(data, symbol=symbol, exchange="SYNTH", interval="5m", source="synthetic", notes="deterministic synthetic smoke dataset")
    return data, manifest


# Phase 1A.2 active dataset contract overlay. Kept in this module so existing imports
# continue to work while preserving the original Phase 1 implementation above.
from dataclasses import field as _field  # noqa: E402
from datetime import timezone as _timezone  # noqa: E402

from .config import DATASET_MANIFEST_VERSION, QUALITY_REPORT_VERSION  # noqa: E402


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    count: int
    samples: tuple[str, ...] = ()
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class QualityReport:
    report_id: str
    valid: bool
    status: str
    issue_count: int
    issues: tuple[QualityIssue, ...]
    schema_version: str = QUALITY_REPORT_VERSION

    def as_dict(self) -> dict[str, object]:
        result = self.__dict__.copy()
        result["issues"] = [issue.as_dict() for issue in self.issues]
        return result


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    dataset_hash_full: str
    dataset_hash_algorithm: str
    symbol: str
    exchange: str
    canonical_instrument_id: str | None
    interval: str
    source_type: str
    source_name: str
    provider_name: str | None
    provider_version: str | None
    source_url: str | None
    local_source_path: str | None
    acquired_at: str
    registered_at: str
    start_timestamp: str
    end_timestamp: str
    timezone: str
    currency: str | None
    row_count: int
    columns: tuple[str, ...]
    session_policy_capabilities: tuple[str, ...]
    quality_status: str
    quality_report_id: str
    quality_report_path: str | None = None
    notes: str = ""
    schema_version: str = "phase1a2_dataset_schema_v1"
    dataset_manifest_version: str = DATASET_MANIFEST_VERSION
    lineage: dict[str, str] = _field(default_factory=lambda: {"stage": "curated", "raw_dataset_id": ""})

    @property
    def sha256(self) -> str:
        return self.dataset_hash_full

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _now_utc_iso() -> str:
    return pd.Timestamp.now(tz=_timezone.utc).isoformat()


def _sample_timestamps(data: pd.DataFrame, mask: pd.Series, limit: int = 5) -> tuple[str, ...]:
    if "timestamp" not in data:
        return ()
    return tuple(str(value) for value in data.loc[mask.fillna(False), "timestamp"].head(limit))


def _quality_issue(code: str, severity: str, count: int, samples: tuple[str, ...] = (), message: str = "") -> QualityIssue | None:
    return QualityIssue(code, severity, int(count), samples, message) if int(count) else None


def session_gap_report(frame: pd.DataFrame, *, interval_minutes: int = 5) -> list[QualityIssue]:
    data = canonicalize_bars(frame).dropna(subset=["timestamp"]).sort_values("timestamp")
    if data.empty:
        return []
    timestamps = pd.to_datetime(data["timestamp"]).dt.tz_convert("Asia/Kolkata")
    interval = timedelta(minutes=interval_minutes)
    missing_inside = 0
    outside = 0
    unknown_gaps = 0
    samples_inside: list[str] = []
    samples_outside: list[str] = []
    samples_unknown: list[str] = []
    for timestamp in timestamps:
        minutes = timestamp.hour * 60 + timestamp.minute
        if timestamp.weekday() >= 5 or minutes < 9 * 60 + 15 or minutes > 15 * 60 + 25 or minutes % interval_minutes:
            outside += 1
            if len(samples_outside) < 5:
                samples_outside.append(timestamp.isoformat())
    for previous, current in zip(timestamps.iloc[:-1], timestamps.iloc[1:]):
        gap = current - previous
        if previous.date() == current.date() and gap > interval:
            missing_inside += max(1, int(gap / interval) - 1)
            if len(samples_inside) < 5:
                samples_inside.append(current.isoformat())
        elif previous.date() != current.date() and previous.weekday() < 5 and current.weekday() < 5:
            unknown_gaps += 1
            if len(samples_unknown) < 5:
                samples_unknown.append(f"{previous.isoformat()} -> {current.isoformat()}")
    issues: list[QualityIssue] = []
    if missing_inside:
        issues.append(QualityIssue("MISSING_SESSION_BAR", "warning", missing_inside, tuple(samples_inside), "Expected five-minute market bars are missing inside a session."))
    if outside:
        issues.append(QualityIssue("OUTSIDE_SESSION_BAR", "warning", outside, tuple(samples_outside), "Bars appear outside the regular Indian equity session or on weekends."))
    if unknown_gaps:
        issues.append(QualityIssue("UNKNOWN_SESSION_GAP", "warning", unknown_gaps, tuple(samples_unknown), "Calendar/holiday gaps are reported but not inferred as errors in Phase 1A.2."))
    return issues


def quality_report(frame: pd.DataFrame) -> QualityReport:
    try:
        data = canonicalize_bars(frame)
    except DataQualityError as error:
        digest = hashlib.sha256(str(error).encode("utf-8")).hexdigest()
        issue = QualityIssue("MISSING_MANDATORY_COLUMN", "error", 1, (), str(error))
        return QualityReport(f"quality_{digest[:16]}", False, "error", 1, (issue,))
    invalid_high = data["high"] < data[["open", "close", "low"]].max(axis=1)
    invalid_low = data["low"] > data[["open", "close", "high"]].min(axis=1)
    issues = [
        _quality_issue("INVALID_TIMESTAMP", "error", data["timestamp"].isna().sum(), message="Timestamp could not be parsed."),
        _quality_issue("NAN_OHLC", "error", data[["open", "high", "low", "close"]].isna().any(axis=1).sum(), _sample_timestamps(data, data[["open", "high", "low", "close"]].isna().any(axis=1)), "Open/high/low/close contains missing or nonnumeric values."),
        _quality_issue("NAN_VOLUME", "warning", data["volume"].isna().sum(), _sample_timestamps(data, data["volume"].isna()), "Volume is missing or nonnumeric."),
        _quality_issue("DUPLICATE_TIMESTAMP", "error", data["timestamp"].duplicated().sum(), _sample_timestamps(data, data["timestamp"].duplicated()), "Duplicate timestamps found."),
        _quality_issue("OUT_OF_ORDER", "error", 0 if data["timestamp"].is_monotonic_increasing else 1, message="Timestamps are not ascending."),
        _quality_issue("NEGATIVE_PRICE", "error", (data[["open", "high", "low", "close"]] < 0).any(axis=1).sum(), _sample_timestamps(data, (data[["open", "high", "low", "close"]] < 0).any(axis=1)), "Negative OHLC price found."),
        _quality_issue("NEGATIVE_VOLUME", "error", (data["volume"] < 0).sum(), _sample_timestamps(data, data["volume"] < 0), "Negative volume found."),
        _quality_issue("INVALID_HIGH", "error", invalid_high.sum(), _sample_timestamps(data, invalid_high), "High is below open, close, or low."),
        _quality_issue("INVALID_LOW", "error", invalid_low.sum(), _sample_timestamps(data, invalid_low), "Low is above open, close, or high."),
        _quality_issue("ZERO_VOLUME_PATTERN", "warning", int(len(data)) if len(data) >= 20 and (data["volume"] == 0).mean() > 0.8 else 0, message="More than 80% of bars have zero volume."),
        _quality_issue("EXTREME_DISCONTINUITY", "warning", (data["close"].pct_change().abs() > 0.35).sum(), _sample_timestamps(data, data["close"].pct_change().abs() > 0.35), "Close-to-close move exceeds 35%."),
    ]
    clean_issues = [issue for issue in issues if issue]
    clean_issues.extend(session_gap_report(data))
    status = "error" if any(issue.severity == "error" for issue in clean_issues) else "warning" if clean_issues else "valid"
    digest = hashlib.sha256(json.dumps([issue.as_dict() for issue in clean_issues], sort_keys=True).encode("utf-8")).hexdigest()
    return QualityReport(f"quality_{digest[:16]}", status != "error", status, len(clean_issues), tuple(clean_issues))


def validate_bars(frame: pd.DataFrame) -> list[str]:
    return [issue.message or issue.code for issue in quality_report(frame).issues]


def build_manifest(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    interval: str,
    source: str,
    notes: str = "",
    source_type: str | None = None,
    provider_name: str | None = None,
    provider_version: str | None = None,
    source_url: str | None = None,
    local_source_path: str | None = None,
    currency: str | None = None,
    acquired_at: str | None = None,
) -> DatasetManifest:
    data = canonicalize_bars(frame)
    report = quality_report(data)
    sha = dataset_hash(data)
    registered_at = _now_utc_iso()
    return DatasetManifest(
        dataset_id=f"{symbol}_{interval}_{sha[:16]}",
        dataset_hash_full=sha,
        dataset_hash_algorithm="sha256",
        symbol=symbol,
        exchange=exchange,
        canonical_instrument_id=f"{exchange}:{symbol}" if exchange and symbol else None,
        interval=interval,
        source_type=source_type or source.split(":", 1)[0],
        source_name=source,
        provider_name=provider_name,
        provider_version=provider_version,
        source_url=source_url,
        local_source_path=local_source_path,
        acquired_at=acquired_at or registered_at,
        registered_at=registered_at,
        start_timestamp=data["timestamp"].iloc[0].isoformat(),
        end_timestamp=data["timestamp"].iloc[-1].isoformat(),
        timezone="Asia/Kolkata",
        currency=currency,
        row_count=len(data),
        columns=tuple(data.columns),
        session_policy_capabilities=("cross_session_allowed", "same_session_only"),
        quality_status=report.status,
        quality_report_id=report.report_id,
        notes=notes,
    )


def load_csv_dataset(path: str | Path, *, symbol: str = "CSV", exchange: str = "CSV", interval: str = "5m") -> tuple[pd.DataFrame, DatasetManifest, QualityReport]:
    source_path = Path(path)
    frame = canonicalize_bars(pd.read_csv(source_path))
    report = quality_report(frame)
    manifest = build_manifest(frame, symbol=symbol, exchange=exchange, interval=interval, source=f"csv:{source_path.name}", source_type="csv", local_source_path=source_path.name, notes="local CSV benchmark dataset")
    return frame, manifest, report


def synthetic_market_data(rows: int = 620, *, symbol: str = "SYNTH") -> tuple[pd.DataFrame, DatasetManifest]:
    start = pd.Timestamp("2026-01-05 09:15", tz="Asia/Kolkata")
    timestamps = []
    day = start
    while len(timestamps) < rows:
        current = pd.Timestamp(day.date().isoformat() + " 09:15", tz="Asia/Kolkata")
        for _ in range(75):
            timestamps.append(current)
            current += timedelta(minutes=5)
            if len(timestamps) >= rows:
                break
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    closes = []
    price = 100.0
    for index in range(rows):
        price += 0.018 + ((index % 17) - 8) * 0.006
        closes.append(round(price, 4))
    data = pd.DataFrame({
        "timestamp": timestamps,
        "open": [round(value - 0.08, 4) for value in closes],
        "high": [round(value + 0.18, 4) for value in closes],
        "low": [round(value - 0.22, 4) for value in closes],
        "close": closes,
        "volume": [1000 + (index % 29) * 10 for index in range(rows)],
        "amount": [round(closes[index] * (1000 + (index % 29) * 10), 2) for index in range(rows)],
    })
    manifest = build_manifest(data, symbol=symbol, exchange="SYNTH", interval="5m", source="synthetic", source_type="synthetic", provider_name="Kronos Copilot synthetic generator", provider_version=DATASET_MANIFEST_VERSION, currency="INR", notes="deterministic synthetic smoke dataset; not real market evidence")
    return data, manifest
