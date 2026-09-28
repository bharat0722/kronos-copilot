"""Product-facing market data boundary built on the Phase 2A providers."""

from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pandas as pd

from .market_data import (
    CanonicalInstrument,
    FallbackProvider,
    MarketDataRequest,
    ProviderError,
    ProviderRegistry,
    ProviderResult,
    YahooProvider,
    canonical_instrument,
    provider_cache_key,
    provider_quality_contract,
)


class MarketDataError(ValueError):
    def __init__(self, code: str, message: str, *, provider: str | None = None,
                 attempts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.attempts = attempts or []

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "provider": self.provider,
                "attempts": deepcopy(self.attempts)}


class MarketDataService:
    """Resolve, fetch, validate, and briefly cache live market bars."""

    def __init__(self, registry: ProviderRegistry | None = None, *, cache_ttl_seconds: float = 30,
                 health_stale_seconds: float = 300):
        if registry is None:
            registry = ProviderRegistry()
            registry.register(YahooProvider())
        self._registry = registry
        self._cache_ttl = cache_ttl_seconds
        self._health_stale_seconds = health_stale_seconds
        self._cache: dict[str, tuple[float, ProviderResult]] = {}
        self._health: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def resolve_symbol(self, symbol: str, exchange: str = "NSE") -> CanonicalInstrument:
        clean = symbol.strip().upper()
        selected_exchange = exchange.strip().upper()
        if selected_exchange not in {"NSE", "BSE"}:
            raise MarketDataError("INVALID_EXCHANGE", "Choose NSE or BSE.")
        if ":" in clean:
            prefix, clean = clean.split(":", 1)
            if prefix not in {"NSE", "BSE"}:
                raise MarketDataError("INVALID_SYMBOL", "Choose an NSE or BSE equity symbol.")
            selected_exchange = prefix
        if clean.startswith("^"):
            if not re.fullmatch(r"\^[A-Z0-9\-]{1,19}", clean):
                raise MarketDataError("INVALID_SYMBOL", "Choose a standard NSE or BSE index symbol.")
            return canonical_instrument(clean, selected_exchange)
        if not re.fullmatch(r"[A-Z0-9.\-]{1,20}", clean):
            raise MarketDataError("INVALID_SYMBOL", "Choose a standard NSE or BSE equity symbol.")
        if "." in clean and not clean.endswith((".NS", ".BO")):
            raise MarketDataError("INVALID_SYMBOL", "Choose a standard NSE or BSE equity symbol.")
        return canonical_instrument(clean, selected_exchange)

    @staticmethod
    def _copy_result(result: ProviderResult, *, cache_hit: bool) -> ProviderResult:
        return replace(
            result,
            bars=result.bars.copy(deep=True),
            provenance={**deepcopy(result.provenance), "cache_hit": cache_hit},
            quality=deepcopy(result.quality),
            health=deepcopy(result.health),
        )

    def _record_failure(self, provider: str, code: str, latency_ms: int) -> None:
        with self._lock:
            previous = self._health.get(provider, {})
            failures = int(previous.get("consecutive_failures", 0)) + 1
            self._health[provider] = {
                "provider": provider,
                "status": "DEGRADED" if code == "INVALID_DATA" and failures == 1 else "FAILED",
                "last_success": previous.get("last_success"),
                "last_failure": pd.Timestamp.now(tz="UTC").isoformat(),
                "latency_ms": latency_ms,
                "consecutive_failures": failures,
                "error_class": code,
            }

    def _record_success(self, provider: str, quality: dict[str, Any], latency_ms: int) -> dict[str, Any]:
        with self._lock:
            previous = self._health.get(provider, {})
            health = {
                "provider": provider,
                "status": "HEALTHY" if quality["state"] == "PASS" else "DEGRADED",
                "last_success": pd.Timestamp.now(tz="UTC").isoformat(),
                "last_failure": previous.get("last_failure"),
                "latency_ms": latency_ms,
                "consecutive_failures": 0,
                "error_class": None,
            }
            self._health[provider] = health
            return health.copy()

    def get_bars(self, request: MarketDataRequest, *, provider: str = "yahoo",
                 fallback_providers: tuple[str, ...] = ()) -> ProviderResult:
        instrument = self.resolve_symbol(request.symbol, request.exchange)
        if request.interval != "5m" or request.start or request.end or request.adjustment != "unadjusted":
            raise MarketDataError("UNSUPPORTED_REQUEST", "This live data path supports recent unadjusted five-minute bars only.")
        normalized = replace(request, symbol=instrument.symbol, exchange=instrument.exchange)
        chain = tuple(dict.fromkeys((provider, *fallback_providers)))
        try:
            selected = [self._registry.get(name) for name in chain]
        except KeyError as error:
            raise MarketDataError("PROVIDER_UNAVAILABLE", "Market data provider is unavailable.", provider=str(error)) from error
        versions = "|".join(str(getattr(item, "cache_version", "unknown")) for item in selected)
        key = provider_cache_key(">".join(chain), normalized, versions)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._cache_ttl:
                return self._copy_result(cached[1], cache_hit=True)
        started = time.monotonic()
        try:
            source = FallbackProvider(selected) if len(selected) > 1 else selected[0]
            result = source.get_historical(normalized)
            if result.provider not in chain:
                raise ProviderError("PROVIDER_IDENTITY_MISMATCH", provider)
            if result.bars.empty:
                raise ProviderError("NO_DATA", result.provider)
            try:
                quality = provider_quality_contract(
                    result.bars, request=normalized, provider=result.provider,
                    retrieved_at=result.provenance.get("retrieved_at"),
                )
            except Exception as error:
                raise ProviderError("INVALID_DATA", result.provider) from error
            if quality["state"] == "FAIL":
                raise ProviderError("INVALID_DATA", result.provider)
            for failure in result.provenance.get("fallback_failures", []):
                self._record_failure(failure["provider"], failure["code"], failure["latency_ms"])
            health = self._record_success(result.provider, quality, int((time.monotonic() - started) * 1000))
            result = replace(
                result,
                quality=quality,
                health=health,
                provenance={**result.provenance, "canonical_instrument_id": instrument.canonical_id,
                            "requested_provider_chain": list(chain), "cache_key": key,
                            "source_symbol": result.provenance.get("provider_symbol", instrument.symbol)},
            )
        except ProviderError as error:
            attempts = error.attempts or [{"provider": error.provider, "code": error.code,
                                           "latency_ms": int((time.monotonic() - started) * 1000)}]
            for failure in attempts:
                self._record_failure(failure["provider"], failure["code"], failure["latency_ms"])
            symbol = instrument.provider_symbols["yahoo"]
            message = (f"No recent five-minute data was found for {symbol}." if error.code == "NO_DATA"
                       else f"Market data failed validation for {symbol}." if error.code == "INVALID_DATA"
                       else f"No five-minute data is currently available for {symbol}.")
            raise MarketDataError(error.code, message, provider=error.provider, attempts=attempts) from error
        except Exception as error:
            self._record_failure(provider, "UPSTREAM_ERROR", int((time.monotonic() - started) * 1000))
            raise MarketDataError("PROVIDER_FAILURE", f"No five-minute data is currently available for {instrument.provider_symbols['yahoo']}.", provider=provider) from error
        with self._lock:
            if len(self._cache) >= 128:
                self._cache = {cache_key: entry for cache_key, entry in self._cache.items()
                               if time.monotonic() - entry[0] < self._cache_ttl}
                if len(self._cache) >= 128:
                    self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic(), self._copy_result(result, cache_hit=False))
        return self._copy_result(result, cache_hit=False)

    def get_provider_health(self, provider: str = "yahoo") -> dict[str, Any]:
        try:
            selected = self._registry.get(provider)
        except KeyError as error:
            raise MarketDataError("PROVIDER_UNAVAILABLE", "Market data provider is unavailable.", provider=provider) from error
        with self._lock:
            health = self._health.get(provider)
        if health is None:
            return selected.health_check().copy()
        current = health.copy()
        if current["status"] != "FAILED" and current.get("last_success"):
            age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(current["last_success"])
            if age.total_seconds() >= self._health_stale_seconds:
                current["status"] = "STALE"
        return current
