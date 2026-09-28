"""Local medallion observer tests; provider responses are synthetic."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.product_pipeline import ProductPipeline
from research.market_data import MarketDataRequest, ProviderResult


class ProductPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = ProductPipeline(self.root)
        times = pd.date_range("2026-08-01 09:15", periods=400, freq="5min", tz="Asia/Kolkata")
        self.bars = pd.DataFrame({"timestamp": times, "open": [100 + i / 100 for i in range(400)],
                                  "high": [100.2 + i / 100 for i in range(400)],
                                  "low": [99.8 + i / 100 for i in range(400)],
                                  "close": [100 + i / 100 for i in range(400)],
                                  "volume": [1000] * 400, "amount": [100000] * 400})

    def provider_result(self, raw: str | None = "provider-native-bars") -> ProviderResult:
        return ProviderResult(provider="yahoo", request=MarketDataRequest("TEST.NS"),
                              bars=self.bars, provenance={"source_symbol": "TEST.NS",
                                  "retrieved_at": "2026-08-01T12:00:00+00:00", "cache_hit": False},
                              quality={"state": "PASS", "issues": []},
                              health={"status": "HEALTHY", "latency_ms": 42}, raw_payload=raw)

    def test_capture_and_gold_do_not_mutate_forecast(self) -> None:
        self.assertEqual(self.pipeline.snapshot()["stages"]["source"]["status"], "STALE")
        capture = self.pipeline.capture(self.provider_result())
        first = self.pipeline.snapshot()
        self.assertEqual(first["stages"]["bronze"]["status"], "HEALTHY")
        self.assertEqual(first["stages"]["silver"]["rows"], 400)
        self.assertEqual(first["stages"]["gold"]["status"], "STALE")
        forecast = [{"timestamp": timestamp.isoformat(), "close": 104.0 + i / 100}
                    for i, timestamp in enumerate(pd.date_range("2026-08-02", periods=24, freq="5min", tz="Asia/Kolkata"))]
        original = json.dumps(forecast, sort_keys=True)
        context = self.bars.rename(columns={"timestamp": "timestamps"})
        self.pipeline.complete(capture, context, {"chart": {"forecast": forecast},
                                                   "summary_fingerprint": "saved", "model": "Kronos-base"})
        self.assertEqual(json.dumps(forecast, sort_keys=True), original)
        latest = json.loads((self.root / "latest.json").read_text(encoding="utf-8"))
        self.assertTrue((self.root / latest["bronze"]["path"]).is_file())
        self.assertTrue((self.root / latest["silver"]["path"]).is_file())
        gold = json.loads((self.root / latest["gold"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(gold["context"]["rows"], 400)
        self.assertTrue(gold["technicals"]["analysis_version"].startswith("phase3_technical_intelligence@"))
        self.assertEqual(gold["kronos_output"]["forecast_bars"], 24)
        self.assertEqual(gold["ensemble_output"]["status"], "RESEARCH_ONLY")
        self.assertEqual(len(gold["evidence"]), 12)
        self.assertEqual(self.pipeline.snapshot()["stages"]["gold"]["status"], "HEALTHY")
        self.assertNotIn("bronze", self.pipeline.snapshot())

    def test_missing_native_capture_is_visible(self) -> None:
        self.pipeline.capture(self.provider_result(raw=None))
        self.assertEqual(self.pipeline.snapshot()["stages"]["bronze"]["status"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
