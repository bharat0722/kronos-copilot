"""Provider-independent market-data contracts and Yahoo adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from typing import Any, Protocol

import numpy as np
import pandas as pd

from .datasets import canonicalize_bars, quality_report


INDIA_TZ = "Asia/Kolkata"
BAR_SCHEMA_VERSION = "phase2a_market_bar_v1"
PROVIDER_SCHEMA_VERSION = "phase2a_provider_registry_v1"
CANONICAL_BAR_COLUMNS = (
    "symbol", "exchange", "timestamp", "open", "high", "low", "close",
    "volume", "amount", "interval", "currency", "provider",
    "adjustment_status", "retrieved_at",
)


class ProviderError(RuntimeError):
    def __init__(self, code: str, provider: str, *, attempts: list[dict[str, Any]] | None = None):
        super().__init__(f"{provider}: {code}")
        self.code = code
        self.provider = provider
        self.attempts = attempts or []


@dataclass(frozen=True)
class CanonicalInstrument:
    canonical_id: str
    symbol: str
    exchange: str
    instrument_type: str = "EQUITY"
    currency: str = "INR"
    isin: str | None = None
    provider_symbols: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketDataRequest:
    symbol: str
    exchange: str = "NSE"
    interval: str = "5m"
    start: str | None = None
    end: str | None = None
    adjustment: str = "unadjusted"

    def canonical(self) -> CanonicalInstrument:
        return canonical_instrument(self.symbol, self.exchange)


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    request: MarketDataRequest
    bars: pd.DataFrame
    provenance: dict[str, Any]
    quality: dict[str, Any]
    health: dict[str, Any]
    raw_payload: str | None = None

    def as_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": BAR_SCHEMA_VERSION,
            "provider": self.provider,
            "request": asdict(self.request),
            "row_count": int(len(self.bars)),
            "provenance": self.provenance,
            "quality": self.quality,
            "health": self.health,
        }


class MarketDataProvider(Protocol):
    name: str

    def get_historical(self, request: MarketDataRequest) -> ProviderResult:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


def yahoo_symbol(symbol: str, exchange: str) -> str:
    clean = symbol.strip().upper()
    if clean.endswith((".NS", ".BO")):
        return clean
    suffix = ".NS" if exchange.strip().upper() == "NSE" else ".BO"
    return f"{clean}{suffix}"


def canonical_instrument(symbol: str, exchange: str = "NSE") -> CanonicalInstrument:
    clean = symbol.strip().upper()
    if clean.startswith("^"):
        resolved_exchange = {"^NSEI": "NSE", "^BSESN": "BSE"}.get(clean, exchange.strip().upper())
        return CanonicalInstrument(
            canonical_id=f"{resolved_exchange}:{clean}", symbol=clean,
            exchange=resolved_exchange, instrument_type="INDEX",
            provider_symbols={"yahoo": clean},
        )
    provider_symbol = yahoo_symbol(symbol, exchange)
    base = provider_symbol.rsplit(".", 1)[0]
    resolved_exchange = "NSE" if provider_symbol.endswith(".NS") else "BSE" if provider_symbol.endswith(".BO") else exchange.upper()
    return CanonicalInstrument(
        canonical_id=f"{resolved_exchange}:{base}",
        symbol=base,
        exchange=resolved_exchange,
        provider_symbols={"yahoo": provider_symbol},
    )


def provider_cache_key(provider: str, request: MarketDataRequest, provider_version: str = "unknown") -> str:
    payload = {
        "provider": provider,
        "provider_version": provider_version,
        "symbol": request.canonical().canonical_id,
        "interval": request.interval,
        "start": request.start,
        "end": request.end,
        "adjustment": request.adjustment,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_provider_bars(frame: pd.DataFrame, *, provider: str, request: MarketDataRequest, retrieved_at: str) -> pd.DataFrame:
    data = canonicalize_bars(frame).copy()
    instrument = request.canonical()
    data["symbol"] = instrument.symbol
    data["exchange"] = instrument.exchange
    data["interval"] = request.interval
    data["currency"] = instrument.currency
    data["provider"] = provider
    data["adjustment_status"] = request.adjustment
    data["retrieved_at"] = retrieved_at
    if "amount" not in data.columns:
        data["amount"] = data["close"] * data["volume"]
    return data[list(CANONICAL_BAR_COLUMNS)]


def provider_quality_contract(
    frame: pd.DataFrame, *, request: MarketDataRequest | None = None,
    provider: str | None = None, retrieved_at: str | None = None,
) -> dict[str, Any]:
    missing = [column for column in CANONICAL_BAR_COLUMNS if column not in frame.columns]
    if missing:
        return {
            "schema_version": "phase2b_quality_contract_v1", "state": "FAIL", "status": "FAIL",
            "valid": False, "issue_count": 1,
            "issues": [{"code": "MISSING_CANONICAL_COLUMN", "severity": "error", "count": len(missing), "samples": missing}],
            "market_closure_count": 0,
        }
    if frame.empty:
        return {
            "schema_version": "phase2b_quality_contract_v1", "state": "FAIL", "status": "FAIL",
            "valid": False, "issue_count": 1,
            "issues": [{"code": "EMPTY_BARS", "severity": "error", "count": 1, "samples": []}],
            "market_closure_count": 0,
        }
    report = quality_report(frame)
    closures = sum(issue.count for issue in report.issues if issue.code == "UNKNOWN_SESSION_GAP")
    issues = [issue.as_dict() for issue in report.issues if issue.code != "UNKNOWN_SESSION_GAP"]

    def add_issue(code: str, severity: str, count: int) -> None:
        if count:
            issues.append({"code": code, "severity": severity, "count": int(count), "samples": []})

    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    add_issue("NON_POSITIVE_OR_NONFINITE_PRICE", "error", int((~np.isfinite(prices) | (prices <= 0)).any(axis=1).sum()))
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    add_issue("NONFINITE_VOLUME", "warning", int((~np.isfinite(volume.to_numpy(dtype=float, na_value=np.nan))).sum()))
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    amount_values = amount.to_numpy(dtype=float, na_value=np.nan)
    add_issue("INVALID_AMOUNT", "warning", int((~np.isfinite(amount_values) | (amount_values < 0)).sum()))
    try:
        timestamps = pd.to_datetime(frame["timestamp"], errors="coerce")
        timezone_ok = str(timestamps.dt.tz) == INDIA_TZ
        if timezone_ok:
            same_session = timestamps.dt.date.eq(timestamps.shift().dt.date)
            gaps = timestamps.diff().dt.total_seconds().div(60)
            add_issue("IRREGULAR_INTRADAY_INTERVAL", "error", int((same_session & gaps.notna() & ((gaps < 5) | (gaps % 5 != 0))).sum()))
    except (AttributeError, TypeError, ValueError):
        timezone_ok = False
        timestamps = pd.Series(dtype="datetime64[ns]")
    add_issue("INVALID_TIMEZONE", "error", 0 if timezone_ok else 1)
    if request is not None:
        identity = request.canonical()
        for column, expected in (
            ("symbol", identity.symbol), ("exchange", identity.exchange),
            ("interval", request.interval), ("currency", identity.currency),
            ("adjustment_status", request.adjustment),
        ):
            add_issue("INCONSISTENT_" + column.upper(), "error", int(frame[column].ne(expected).sum()))
    if provider is not None:
        add_issue("INCONSISTENT_PROVIDER", "error", int(frame["provider"].ne(provider).sum()))
    if retrieved_at and timezone_ok and not timestamps.empty:
        checked = pd.Timestamp(retrieved_at).tz_convert(INDIA_TZ)
        latest = timestamps.max()
        market_open = checked.weekday() < 5 and (9, 15) <= (checked.hour, checked.minute) < (15, 30)
        limit = timedelta(minutes=30) if market_open else timedelta(days=7)
        add_issue("STALE_MARKET_BARS", "warning", int(checked - latest > limit))
    state = "FAIL" if any(issue["severity"] == "error" for issue in issues) else "WARN" if issues else "PASS"
    return {
        "schema_version": "phase2b_quality_contract_v1", "state": state, "status": state,
        "valid": state != "FAIL", "issue_count": len(issues), "issues": issues,
        "market_closure_count": closures,
        "checks": ["canonical_schema", "timestamp_ordering", "duplicates", "finite_positive_ohlc",
                   "ohlc_relationship", "volume", "amount", "interval", "timezone",
                   "session_bounds", "identity", "freshness"],
    }


class YahooProvider:
    name = "yahoo"

    def __init__(self, yf_module: Any | None = None):
        self._yf = yf_module

    def _module(self) -> Any:
        if self._yf is not None:
            return self._yf
        import yfinance as yf
        return yf

    @property
    def cache_version(self) -> str:
        return f"yfinance:{getattr(self._module(), '__version__', 'unknown')}:history_1mo_v1"

    def get_historical(self, request: MarketDataRequest) -> ProviderResult:
        yf = self._module()
        symbol = request.canonical().provider_symbols["yahoo"]
        started = pd.Timestamp.now(tz="UTC")
        try:
            raw = yf.Ticker(symbol).history(period="1mo", interval=request.interval, auto_adjust=False)
        except Exception as error:
            raise ProviderError("UPSTREAM_ERROR", self.name) from error
        retrieved_at = pd.Timestamp.now(tz="UTC").isoformat()
        if raw.empty:
            raise ProviderError("NO_DATA", self.name)
        if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
            raise ProviderError("MALFORMED_TIMESTAMPS", self.name)
        raw_payload = raw.to_csv(index=True)
        raw = raw.reset_index().rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        if "timestamp" not in raw.columns:
            raw = raw.rename(columns={raw.columns[0]: "timestamp"})
        try:
            bars = normalize_provider_bars(raw, provider=self.name, request=request, retrieved_at=retrieved_at)
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("MALFORMED_BARS", self.name) from error
        return ProviderResult(
            provider=self.name,
            request=request,
            bars=bars,
            provenance={
                "provider": "Yahoo Finance via yfinance",
                "provider_symbol": symbol,
                "provider_version": getattr(yf, "__version__", "unknown"),
                "retrieved_at": retrieved_at,
                "adjustment": request.adjustment,
                "interval": request.interval,
                "history_period": "1mo",
                "amount_method": "close_times_volume_estimate",
                "timezone": INDIA_TZ,
            },
            quality=provider_quality_contract(bars, request=request, provider=self.name, retrieved_at=retrieved_at),
            health={"status": "HEALTHY", "last_success": retrieved_at, "latency_ms": int((pd.Timestamp.now(tz="UTC") - started).total_seconds() * 1000)},
            raw_payload=raw_payload,
        )

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "STALE", "last_success": None,
                "last_failure": None, "latency_ms": None, "consecutive_failures": 0,
                "network_check": "not_run"}


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> MarketDataProvider:
        return self._providers[name]

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": PROVIDER_SCHEMA_VERSION, "providers": sorted(self._providers)}


class FallbackProvider:
    name = "fallback"

    def __init__(self, providers: list[MarketDataProvider]):
        self.providers = providers

    def get_historical(self, request: MarketDataRequest) -> ProviderResult:
        failures: list[dict[str, Any]] = []
        for provider in self.providers:
            started = pd.Timestamp.now(tz="UTC")
            try:
                result = provider.get_historical(request)
                if result.provider != provider.name:
                    raise ProviderError("PROVIDER_IDENTITY_MISMATCH", provider.name)
                try:
                    quality = provider_quality_contract(result.bars, request=request, provider=result.provider)
                except Exception as error:
                    raise ProviderError("INVALID_DATA", provider.name) from error
                if quality["state"] == "FAIL":
                    raise ProviderError("INVALID_DATA", provider.name)
                return replace(result, quality=quality, provenance={
                    **result.provenance,
                    "fallback_chain": [p.name for p in self.providers],
                    "fallback_failures": failures.copy(),
                })
            except Exception as error:
                failures.append({"provider": provider.name,
                                 "code": error.code if isinstance(error, ProviderError) else "UPSTREAM_ERROR",
                                 "latency_ms": int((pd.Timestamp.now(tz="UTC") - started).total_seconds() * 1000)})
        raise ProviderError("ALL_PROVIDERS_FAILED", self.name, attempts=failures)

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "DEGRADED", "providers": [provider.health_check() for provider in self.providers]}


def phase2a_architecture_artifacts() -> dict[str, Any]:
    return {
        "provider_registry": {"schema_version": PROVIDER_SCHEMA_VERSION, "active_provider": "yahoo", "future_providers": ["openbb", "broker", "nse_authorized_feed"]},
        "canonical_market_bar_schema": {
            "schema_version": BAR_SCHEMA_VERSION,
            "columns": list(CANONICAL_BAR_COLUMNS),
        },
        "symbol_mapping_rules": {
            "canonical_id": "{exchange}:{base_symbol}",
            "yahoo_nse": "{symbol}.NS",
            "yahoo_bse": "{symbol}.BO",
            "rule": "Provider suffixes are mappings, not canonical identity.",
        },
        "provider_health_schema": {
            "states": ["HEALTHY", "DEGRADED", "FAILED", "STALE"],
            "fields": ["provider", "last_success", "last_failure", "latency_ms", "error_class"],
        },
        "cache_specification": {
            "key_fields": ["provider", "provider_version", "canonical_symbol", "interval", "start", "end", "adjustment"],
            "rule": "Cache must preserve provider provenance and must not silently mix adjustment modes.",
        },
    }
