"""Focused Phase 2A.2 service and live-path regression checks."""

from __future__ import annotations

import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from research.datasets import synthetic_market_data
from research.market_data import (
    MarketDataRequest, ProviderRegistry, ProviderResult, YahooProvider,
    normalize_provider_bars, provider_quality_contract,
)
from research.market_data_service import MarketDataError, MarketDataService


class FakeYahoo:
    __version__ = "test"

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[tuple[str, dict]] = []

    def Ticker(self, symbol: str):
        parent = self

        class Ticker:
            def history(self, **kwargs):
                parent.calls.append((symbol, kwargs))
                return parent.frame.copy(deep=True)

        return Ticker()


def legacy_yahoo_bars(symbol: str, yf_module) -> tuple[str, pd.DataFrame]:
    """Frozen pre-service Yahoo transformation used only as a regression oracle."""
    source_symbol = f"{symbol.upper()}.NS"
    frame = yf_module.Ticker(source_symbol).history(period="1mo", interval="5m", auto_adjust=False)
    frame = frame.reset_index().rename(columns={
        "Datetime": "timestamps", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True).dt.tz_convert("Asia/Kolkata")
    frame["amount"] = frame["close"] * frame["volume"]
    return source_symbol, frame[["timestamps", "open", "high", "low", "close", "volume", "amount"]].dropna()


class MarketDataServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        bars, _ = synthetic_market_data(rows=400)
        self.raw = bars.rename(columns={
            "timestamp": "Datetime", "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        }).set_index("Datetime")[["Open", "High", "Low", "Close", "Volume"]]
        self.yahoo = FakeYahoo(self.raw)
        registry = ProviderRegistry()
        registry.register(YahooProvider(self.yahoo))
        self.service = MarketDataService(registry, cache_ttl_seconds=30)

    def test_three_symbols_match_legacy_market_bars(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
        from app import server

        with patch.object(server.yf, "Ticker", self.yahoo.Ticker), patch.object(server, "LIVE_MARKET_DATA_SERVICE", self.service):
            for symbol in ("RELIANCE", "TCS", "INFY"):
                with self.subTest(symbol=symbol):
                    legacy_symbol, legacy = legacy_yahoo_bars(symbol, server.yf)
                    result = self.service.get_bars(MarketDataRequest(symbol))
                    service_bars = result.bars.rename(columns={"timestamp": "timestamps"})[server.REQUIRED_COLUMNS].dropna()
                    self.assertEqual(legacy_symbol, result.provenance["provider_symbol"])
                    self.assertEqual(len(legacy), len(service_bars))
                    self.assertEqual(str(legacy.timestamps.dt.tz), str(service_bars.timestamps.dt.tz))
                    self.assertEqual(result.bars.interval.unique().tolist(), ["5m"])
                    pd.testing.assert_frame_equal(legacy.reset_index(drop=True), service_bars.reset_index(drop=True), check_dtype=False)
                    self.assertEqual(self.yahoo.calls[-2][1], self.yahoo.calls[-1][1])
            with patch.object(server, "run_forecast", return_value={"ok": True}) as forecast:
                self.assertEqual(server.fetch_live_forecast("RELIANCE"), {"ok": True})
                self.assertIn("RELIANCE.NS live 5-minute data", forecast.call_args.args)
                self.assertEqual(server.fetch_live_forecast("^NSEI"), {"ok": True})
                self.assertIn("^NSEI live 5-minute data", forecast.call_args.args)
            with patch.object(server, "run_validation", return_value={"ok": True}) as validation:
                self.assertEqual(server.fetch_live_validation("TCS"), {"ok": True})
                self.assertIn("TCS.NS live 5-minute data", validation.call_args.args)

    def test_symbol_resolution_nse_bse_and_validation(self) -> None:
        self.assertEqual(self.service.resolve_symbol(" nse:reliance ").canonical_id, "NSE:RELIANCE")
        self.assertEqual(self.service.resolve_symbol("reliance.bo", "NSE").canonical_id, "BSE:RELIANCE")
        self.assertEqual(self.service.resolve_symbol("^NSEI").instrument_type, "INDEX")
        self.assertEqual(self.service.get_bars(MarketDataRequest("TCS", "BSE")).provenance["provider_symbol"], "TCS.BO")
        with self.assertRaises(MarketDataError) as invalid:
            self.service.get_bars(MarketDataRequest("Not a symbol"))
        self.assertEqual(invalid.exception.code, "INVALID_SYMBOL")

    def test_cache_and_provenance_are_isolated(self) -> None:
        request = MarketDataRequest("INFY")
        first = self.service.get_bars(request)
        first.bars.loc[0, "close"] = -1
        second = self.service.get_bars(request)
        self.assertEqual(len(self.yahoo.calls), 1)
        self.assertFalse(first.provenance["cache_hit"])
        self.assertTrue(second.provenance["cache_hit"])
        self.assertGreater(second.bars.loc[0, "close"], 0)
        self.assertEqual(second.provenance["canonical_instrument_id"], "NSE:INFY")
        self.assertEqual(self.service.get_provider_health()["status"], "DEGRADED")
        self.assertEqual(second.quality["state"], "WARN")
        self.assertEqual(second.provenance["amount_method"], "close_times_volume_estimate")
        self.assertNotEqual(
            self.service.get_bars(MarketDataRequest("INFY", "BSE")).provenance["cache_key"],
            second.provenance["cache_key"],
        )

    def test_invalid_bars_fail_quality_gate(self) -> None:
        self.yahoo.frame.iloc[0, self.yahoo.frame.columns.get_loc("High")] = -1
        with self.assertRaises(MarketDataError) as invalid:
            self.service.get_bars(MarketDataRequest("TCS"))
        self.assertEqual(invalid.exception.code, "INVALID_DATA")

    def test_provider_failure_is_structured(self) -> None:
        self.yahoo.frame = self.yahoo.frame.iloc[:0]
        with self.assertRaises(MarketDataError) as failure:
            self.service.get_bars(MarketDataRequest("INFY"))
        self.assertEqual(failure.exception.code, "NO_DATA")
        self.assertEqual(self.service.get_provider_health()["status"], "FAILED")
        self.assertEqual(self.service.get_provider_health()["consecutive_failures"], 1)
        self.assertIsNotNone(self.service.get_provider_health()["last_failure"])

    def test_quality_pass_warn_fail_and_closures(self) -> None:
        result = self.service.get_bars(MarketDataRequest("INFY"))
        fresh = provider_quality_contract(result.bars, request=result.request, provider="yahoo")
        self.assertEqual(fresh["state"], "PASS")
        self.assertGreater(fresh["market_closure_count"], 0)
        missing = result.bars.drop(index=1).reset_index(drop=True)
        self.assertEqual(provider_quality_contract(missing, request=result.request, provider="yahoo")["state"], "WARN")
        incorrect = result.bars.copy()
        incorrect.loc[0, "symbol"] = "OTHER"
        self.assertEqual(provider_quality_contract(incorrect, request=result.request, provider="yahoo")["state"], "FAIL")

    def test_fallback_rejects_invalid_primary_and_preserves_reasons(self) -> None:
        raw = self.raw.reset_index().rename(columns={
            "Datetime": "timestamp", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })

        class InvalidProvider:
            name = "invalid"
            cache_version = "test-v1"

            def get_historical(self, request):
                bars = normalize_provider_bars(raw, provider=self.name, request=request,
                                               retrieved_at="2026-01-01T00:00:00+00:00")
                bars.loc[0, "high"] = -1
                return ProviderResult(self.name, request, bars, {}, {}, {})

            def health_check(self):
                return {"provider": self.name, "status": "STALE"}

        registry = ProviderRegistry()
        registry.register(InvalidProvider())
        registry.register(YahooProvider(self.yahoo))
        service = MarketDataService(registry)
        result = service.get_bars(MarketDataRequest("RELIANCE"), provider="invalid", fallback_providers=("yahoo",))
        self.assertEqual(result.provider, "yahoo")
        self.assertEqual(result.provenance["fallback_failures"][0]["code"], "INVALID_DATA")
        self.assertEqual(result.provenance["requested_provider_chain"], ["invalid", "yahoo"])
        self.assertEqual(service.get_provider_health("invalid")["status"], "DEGRADED")
        self.assertEqual(service.get_provider_health("invalid")["consecutive_failures"], 1)

    def test_health_stale_and_recovery(self) -> None:
        service = MarketDataService(self.service._registry, health_stale_seconds=0)
        self.assertEqual(service.get_provider_health()["status"], "STALE")
        service.get_bars(MarketDataRequest("TCS"))
        self.assertEqual(service.get_provider_health()["status"], "STALE")
        self.yahoo.frame = self.yahoo.frame.iloc[:0]
        with self.assertRaises(MarketDataError):
            service.get_bars(MarketDataRequest("INFY"))
        self.assertEqual(service.get_provider_health()["status"], "FAILED")
        self.yahoo.frame = self.raw
        service.get_bars(MarketDataRequest("INFY"))
        self.assertEqual(service.get_provider_health()["consecutive_failures"], 0)
        self.assertIsNotNone(service.get_provider_health()["last_success"])

    def test_healthy_provider_without_freshness_warning(self) -> None:
        class CleanProvider:
            name = "clean"

            def get_historical(self, request):
                raw = self_raw.reset_index().rename(columns={
                    "Datetime": "timestamp", "Open": "open", "High": "high",
                    "Low": "low", "Close": "close", "Volume": "volume",
                })
                bars = normalize_provider_bars(raw, provider=self.name, request=request,
                                               retrieved_at="2026-01-01T00:00:00+00:00")
                return ProviderResult(self.name, request, bars, {"provider_symbol": "TCS.NS"}, {}, {})

            def health_check(self):
                return {"provider": self.name, "status": "STALE"}

        self_raw = self.raw
        registry = ProviderRegistry()
        registry.register(CleanProvider())
        service = MarketDataService(registry)
        result = service.get_bars(MarketDataRequest("TCS"), provider="clean")
        self.assertEqual(result.quality["state"], "PASS")
        self.assertEqual(service.get_provider_health("clean")["status"], "HEALTHY")
        self.assertEqual(service.get_provider_health("clean")["consecutive_failures"], 0)

    def test_all_provider_failures_are_structured(self) -> None:
        class EmptyProvider:
            def __init__(self, name):
                self.name = name

            def get_historical(self, request):
                raise RuntimeError("offline")

            def health_check(self):
                return {"provider": self.name, "status": "STALE"}

        registry = ProviderRegistry()
        registry.register(EmptyProvider("first"))
        registry.register(EmptyProvider("second"))
        service = MarketDataService(registry)
        with self.assertRaises(MarketDataError) as failure:
            service.get_bars(MarketDataRequest("INFY"), provider="first", fallback_providers=("second",))
        self.assertEqual(failure.exception.code, "ALL_PROVIDERS_FAILED")
        self.assertEqual([item["provider"] for item in failure.exception.as_dict()["attempts"]], ["first", "second"])
        self.assertEqual(service.get_provider_health("first")["status"], "FAILED")
        self.assertEqual(service.get_provider_health("second")["status"], "FAILED")

    @unittest.skipUnless(os.environ.get("KRONOS_LIVE_YAHOO_REGRESSION") == "1", "requires explicit live Yahoo opt-in")
    def test_live_yahoo_legacy_service_parity(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
        from app import server

        service = MarketDataService(cache_ttl_seconds=0)
        for symbol in ("RELIANCE", "TCS", "INFY"):
            with self.subTest(symbol=symbol):
                legacy_symbol, legacy = legacy_yahoo_bars(symbol, server.yf)
                result = service.get_bars(MarketDataRequest(symbol))
                service_bars = result.bars.rename(columns={"timestamp": "timestamps"})[server.REQUIRED_COLUMNS].dropna()
                self.assertEqual(legacy_symbol, result.provenance["provider_symbol"])
                self.assertEqual(len(legacy), len(service_bars))
                self.assertEqual(str(legacy.timestamps.dt.tz), str(service_bars.timestamps.dt.tz))
                self.assertEqual(result.bars.interval.unique().tolist(), ["5m"])
                pd.testing.assert_frame_equal(legacy.reset_index(drop=True), service_bars.reset_index(drop=True), check_dtype=False)


if __name__ == "__main__":
    unittest.main()
