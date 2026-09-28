"""Focused Phase 3 tests; no provider, model, or network calls."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research.phase3 import _decision, _verify_index, _weights
from research.technical_intelligence import analyze


def bars(n: int = 80) -> pd.DataFrame:
    close = np.linspace(100, 110, n)
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="5min", tz="Asia/Kolkata"),
                         "open": close, "high": close + 0.2, "low": close - 0.2,
                         "close": close, "volume": np.full(n, 1000)})


class Phase3Tests(unittest.TestCase):
    def test_indicators_are_complete_and_historical(self) -> None:
        sample = bars()
        result = analyze(sample)
        self.assertEqual(len(result["indicators"]), 12)
        self.assertEqual(result["regime"] in {"TRENDING_BULL", "TRENDING_BEAR", "SIDEWAYS",
                                                      "HIGH_VOLATILITY", "LOW_VOLATILITY"}, True)
        self.assertEqual(result["as_of"], str(sample["timestamp"].iloc[-1]))
        self.assertTrue(all({"indicator", "value", "signal", "strength", "reason"} <= set(item)
                            for item in result["indicators"]))
        self.assertTrue(all(0 <= item["strength"] <= 1 for item in result["indicators"]))

    def test_rejects_bad_bars(self) -> None:
        sample = bars()
        sample.loc[1, "high"] = 0
        with self.assertRaises(ValueError):
            analyze(sample)
        with self.assertRaises(ValueError):
            analyze(bars(20))

    def test_simplex_weights(self) -> None:
        rows = [{"paths": np.array([[101., 100., 99., 98.], [102., 100., 98., 97.]]),
                 "truth": np.array([101., 102.]), "last": 100.} for _ in range(3)]
        weights = _weights(rows)
        self.assertTrue(all(0 <= x <= 1 for x in weights))
        self.assertAlmostEqual(sum(weights), 1)
        self.assertEqual(weights[0], 1.0)

    def test_gate_can_abstain(self) -> None:
        row = {"key": ("TEST.NS", 24, "cutoff"), "last": 100.,
               "paths": np.array([[100., 100., 100., 100.], [100.05, 100., 100., 100.]]),
               "technical": {"trend": "mixed", "momentum": "mixed"}}
        self.assertEqual(_decision(row, {24: [1., 0., 0., 0.]}, 0.1, False), "NO_STRONG_EDGE")

    def test_incomplete_index_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _verify_index({}, "development")


if __name__ == "__main__":
    unittest.main()
