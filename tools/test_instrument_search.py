"""Deterministic tests for Kronos Copilot's local instrument resolver."""

from __future__ import annotations

import random
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import instrument_search as search  # noqa: E402


class InstrumentSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        start = time.perf_counter()
        cls.index = search.load_index()
        cls.load_ms = (time.perf_counter() - start) * 1000

    def top(self, query: str, exchange: str = "NSE") -> dict[str, object]:
        results = search.search_instruments(query, exchange)
        self.assertTrue(results, f"No results for {query!r}")
        return results[0]

    def assert_top_symbol(self, query: str, expected: str, exchange: str = "NSE") -> None:
        self.assertEqual(self.top(query, exchange)["symbol"], expected)

    def test_hindustan_unilever_resolution(self) -> None:
        for query in ["HUL", "hul", "Hindustan Unilever", "hindustan unilever", "Hindustan Unilever Limited", "HINDUNILVR", "hindunilvr", "HINDUNILVR.NS"]:
            with self.subTest(query=query):
                self.assert_top_symbol(query, "HINDUNILVR.NS")

    def test_reliance_resolution(self) -> None:
        for query in ["Reliance", "reliance", "Reliance Industries", "RIL", "RELIANCE", "RELIANCE.NS", "relian", "relaince"]:
            with self.subTest(query=query):
                self.assert_top_symbol(query, "RELIANCE.NS")

    def test_tcs_resolution(self) -> None:
        for query in ["TCS", "tcs", "Tata Consultancy", "Tata Consultancy Services", "TCS.NS", "tat consult", "tata consultncy"]:
            with self.subTest(query=query):
                self.assert_top_symbol(query, "TCS.NS")

    def test_infosys_resolution(self) -> None:
        for query in ["Infosys", "infosys", "INFY", "infy", "INFY.NS"]:
            with self.subTest(query=query):
                self.assert_top_symbol(query, "INFY.NS")

    def test_state_bank_resolution(self) -> None:
        for query in ["SBI", "sbi", "State Bank", "State Bank India", "State Bank of India", "SBIN", "SBIN.NS"]:
            with self.subTest(query=query):
                self.assert_top_symbol(query, "SBIN.NS")

    def test_ambiguity_is_returned_as_choices(self) -> None:
        results = search.search_instruments("HDFC", "NSE")
        symbols = {item["symbol"] for item in results}
        self.assertGreaterEqual(len(results), 3)
        self.assertIn("HDFCBANK.NS", symbols)
        self.assertTrue({"HDFCLIFE.NS", "HDFCAMC.NS"} & symbols)

    def test_general_behaviour(self) -> None:
        self.assert_top_symbol("  hindustan   unilever ltd. ", "HINDUNILVR.NS")
        self.assert_top_symbol("HINDUNILVR.BO", "HINDUNILVR.BO", "BSE")
        self.assert_top_symbol("VI", "IDEA.NS")
        self.assertEqual(search.search_instruments("zzznonsensecompany", "NSE"), [])

    def test_generalization_sample(self) -> None:
        instruments = [item for item in self.index.instruments if item.exchange == "NSE"]
        sample = random.Random(42).sample(instruments, min(120, len(instruments)))
        ticker_hits = 0
        name_hits = 0
        partial_hits = 0
        partial_total = 0
        failures: list[str] = []

        for instrument in sample:
            if any(item["symbol"] == instrument.yahoo_symbol for item in search.search_instruments(instrument.symbol, "NSE")[:3]):
                ticker_hits += 1
            else:
                failures.append(f"ticker:{instrument.symbol}")
            if any(item["symbol"] == instrument.yahoo_symbol for item in search.search_instruments(instrument.company_name, "NSE")[:5]):
                name_hits += 1
            else:
                failures.append(f"name:{instrument.symbol}")
            tokens = search.meaningful_tokens(instrument.company_name)
            if tokens:
                partial_total += 1
                partial = " ".join(tokens[: min(2, len(tokens))])
                if any(item["symbol"] == instrument.yahoo_symbol for item in search.search_instruments(partial, "NSE")[:8]):
                    partial_hits += 1

        self.generalization = {
            "sample_size": len(sample),
            "ticker_discoverable_pct": round(ticker_hits / len(sample) * 100, 2),
            "company_name_discoverable_pct": round(name_hits / len(sample) * 100, 2),
            "partial_name_discoverable_pct": round(partial_hits / max(partial_total, 1) * 100, 2),
            "representative_failures": failures[:8],
        }
        self.assertGreaterEqual(self.generalization["ticker_discoverable_pct"], 98)
        self.assertGreaterEqual(self.generalization["company_name_discoverable_pct"], 95)
        self.assertGreaterEqual(self.generalization["partial_name_discoverable_pct"], 80)

    def test_search_latency(self) -> None:
        queries = ["HUL", "RIL", "Reliance", "SBI", "TCS", "Infosys", "HDFC", "relaince", "tat consultncy", "State Bank India"] * 5
        start = time.perf_counter()
        for query in queries:
            search.search_instruments(query, "NSE")
        avg_ms = (time.perf_counter() - start) * 1000 / len(queries)
        self.performance = {
            "load_ms": round(self.load_ms, 2),
            "average_search_ms": round(avg_ms, 2),
            "instrument_count": len(self.index.instruments),
            "alias_count": self.index.alias_count,
        }
        self.assertLess(avg_ms, 75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
