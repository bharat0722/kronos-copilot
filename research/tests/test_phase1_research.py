from __future__ import annotations

import tempfile
import unittest
import json
import hashlib
from pathlib import Path

import pandas as pd

from research import baselines
from research.datasets import canonicalize_bars, dataset_hash, quality_report, synthetic_market_data, validate_bars
from research.metrics import close_metrics
from research.provenance import stable_seed
from research.regimes import tag_regime
from research.registry import ExperimentRegistry
from research.runner import resume_run, run_profile
from research.profiles import get_profile
from research.specs import build_experiment_spec
from research.stats import bootstrap_ci, paired_comparisons
from research.windows import generate_windows, split_window
from research.market_data import MarketDataRequest, ProviderResult, ProviderRegistry, FallbackProvider, canonical_instrument, normalize_provider_bars, provider_cache_key, phase2a_architecture_artifacts
import research.real_market as real_market
from research.training_data import (
    assert_training_dataset_safe,
    assert_phase1e_training_cutoff,
    generate_kronos_training_windows,
    normalize_raw_intraday,
    protected_evaluation_boundaries,
    to_kronos_training_frame,
    training_hash,
    training_cutoff_spec,
    validate_training_dataset,
    resample_1m_to_5m,
    phase1e_c2_source_audit_metadata,
)


class Phase1ResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bars, self.manifest = synthetic_market_data(rows=620)

    def test_metrics_exact_values(self) -> None:
        context = pd.DataFrame({"close": [10, 11, 12, 13], "timestamp": pd.date_range("2026-01-01", periods=4, tz="Asia/Kolkata")})
        actual = pd.DataFrame({"timestamp": pd.date_range("2026-01-02", periods=3, tz="Asia/Kolkata"), "close": [14, 16, 18]})
        pred = pd.DataFrame({"timestamp": actual["timestamp"], "close": [13, 17, 21]})
        metrics = close_metrics(pred, actual, context)
        self.assertAlmostEqual(metrics["mae"], 5 / 3)
        self.assertAlmostEqual(metrics["rmse"], (11 / 3) ** 0.5)
        self.assertEqual(metrics["directional_match"], True)
        self.assertEqual(metrics["compared_bars"], 3)

    def test_window_boundaries_no_leakage(self) -> None:
        windows = generate_windows(self.bars, symbol="SYNTH", lookback_bars=400, horizon_bars=24, stride_bars=24, max_windows=2)
        self.assertEqual(windows[0].context_start_index, 0)
        self.assertEqual(windows[0].context_end_index, 399)
        self.assertEqual(windows[0].future_start_index, 400)
        self.assertEqual(windows[0].future_end_index, 423)
        context, future = split_window(self.bars, windows[0])
        self.assertLess(context["timestamp"].max(), future["timestamp"].min())

    def test_window_horizons_and_insufficient_rows(self) -> None:
        for horizon in (24, 75, 120):
            windows = generate_windows(self.bars, symbol="SYNTH", lookback_bars=400, horizon_bars=horizon, stride_bars=horizon, max_windows=1)
            self.assertEqual(windows[0].horizon_bars, horizon)
        self.assertEqual(generate_windows(self.bars.head(410), symbol="SYNTH", lookback_bars=400, horizon_bars=24, stride_bars=24), [])

    def test_same_session_policy(self) -> None:
        windows = generate_windows(self.bars, symbol="SYNTH", lookback_bars=400, horizon_bars=24, stride_bars=1, session_policy="same_session_only", max_windows=1)
        self.assertTrue(windows)
        _, future = split_window(self.bars, windows[0])
        self.assertEqual(pd.to_datetime(future["timestamp"]).dt.date.nunique(), 1)

    def test_dataset_validation(self) -> None:
        clean = canonicalize_bars(self.bars)
        self.assertFalse(any(issue.severity == "error" for issue in quality_report(clean).issues))
        bad = clean.copy()
        bad.loc[0, "high"] = bad.loc[0, "low"] - 1
        self.assertIn("High is below open, close, or low.", validate_bars(bad))

    def test_baselines_context_only(self) -> None:
        window = generate_windows(self.bars, symbol="SYNTH", lookback_bars=400, horizon_bars=24, stride_bars=24, max_windows=1)[0]
        context, future = split_window(self.bars, window)
        pred = baselines.persistence(context, future["timestamp"])
        self.assertTrue((pred["close"] == float(context["close"].iloc[-1])).all())
        self.assertEqual(len(baselines.simple_drift(context, future["timestamp"])), 24)
        self.assertEqual(len(baselines.simple_momentum(context, future["timestamp"])), 24)

    def test_regimes(self) -> None:
        up = self.bars.copy()
        up["close"] = range(len(up))
        self.assertEqual(tag_regime(up.tail(400))["trend"], "uptrend")
        flat = self.bars.copy()
        flat["close"] = 100
        self.assertEqual(tag_regime(flat.tail(400))["trend"], "flat")

    def test_registry_resume_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = ExperimentRegistry(Path(temp) / "registry.sqlite3")
            payload = {
                "run_id": "resume_test",
                "system_configuration_id": "kronos_only_v1",
                "dataset_id": "dataset",
                "symbol": "SYNTH",
                "horizon_bars": 24,
                "model_name": "fake",
                "window": {"id": 1},
                "settings": {},
            }
            self.assertTrue(registry.start_experiment("exp1", payload))
            registry.finish_experiment("exp1", {"mae": 1}, {"trend": "flat"})
            self.assertFalse(registry.start_experiment("exp1", payload))
            registry.close()

    def test_fake_runner_integration(self) -> None:
        result = run_profile(get_profile("dry-run"), adapter_name="fake", run_id="unit_fake_runner")
        self.assertGreaterEqual(result["summary"]["success_count"], 4)
        self.assertTrue(Path(result["report_path"]).exists())

    def test_dataset_manifest_full_hash_and_provenance(self) -> None:
        self.assertEqual(len(self.manifest.dataset_hash_full), 64)
        self.assertEqual(self.manifest.dataset_hash_algorithm, "sha256")
        self.assertTrue(self.manifest.acquired_at)
        self.assertTrue(self.manifest.registered_at)
        changed = self.bars.copy()
        changed.loc[0, "close"] += 1
        _, changed_manifest = synthetic_market_data(rows=620)
        changed_manifest = changed_manifest.__class__(**{**changed_manifest.as_dict(), "dataset_hash_full": "different"})
        self.assertNotEqual(self.manifest.dataset_hash_full, changed_manifest.dataset_hash_full)

    def test_scientific_experiment_id_independent_from_run_id(self) -> None:
        window = generate_windows(self.bars, symbol="SYNTH", lookback_bars=400, horizon_bars=24, stride_bars=24, max_windows=1)[0]
        settings = {"temperature": 1.0, "top_k": 0, "top_p": 0.9, "sample_count": 1}
        seed = stable_seed({"dataset_hash": self.manifest.dataset_hash_full, "window": window.window_id})
        kwargs = dict(
            manifest=self.manifest,
            window=window,
            model_name="fake",
            settings=settings,
            system_configuration_id="kronos_only_v1",
            purpose="smoke",
            model_provenance={"model_id": "fake", "model_version": "v1", "tokenizer_id": "none", "tokenizer_version": "none"},
            git={"commit": "abc", "dirty": False},
            seed=seed,
        )
        self.assertEqual(build_experiment_spec(**kwargs).scientific_experiment_id, build_experiment_spec(**kwargs).scientific_experiment_id)

    def test_bootstrap_small_n_and_paired_comparison(self) -> None:
        self.assertEqual(bootstrap_ci([1.0, 2.0])["status"], "INSUFFICIENT_SAMPLE")
        rows = []
        for index in range(5):
            rows.append({"symbol": "SYNTH", "horizon_bars": 24, "cutoff": str(index), "model_name": "kronos", "mae": 1.0})
            rows.append({"symbol": "SYNTH", "horizon_bars": 24, "cutoff": str(index), "model_name": "persistence", "mae": 2.0})
        paired = paired_comparisons(rows)
        self.assertEqual(paired["persistence"]["win_count"], 5)
        self.assertEqual(paired["persistence"]["ci"]["status"], "OK")

    def test_artifacts_interrupt_and_resume(self) -> None:
        run_id = "unit_interrupt_resume"
        interrupted = run_profile(get_profile("smoke"), adapter_name="fake", run_id=run_id, interrupt_after=2, force=True)
        self.assertEqual(interrupted["status"], "interrupted")
        resumed = resume_run(run_id)
        self.assertGreaterEqual(resumed["summary"]["success_count"], 8)
        artifact_root = Path("research/results/runs") / run_id / "artifacts"
        self.assertTrue(artifact_root.exists())

    def test_phase1b_dataset_hash_survives_csv_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bars.csv.gz"
            bars = canonicalize_bars(self.bars)
            expected = dataset_hash(bars)
            bars.to_csv(path, index=False, compression="gzip")
            reloaded = pd.read_csv(path, compression="gzip")
            self.assertEqual(expected, dataset_hash(reloaded))

    def test_phase1b_locked_subset_requires_unlock_token(self) -> None:
        original_lock_path = real_market.LOCK_PATH
        try:
            with tempfile.TemporaryDirectory() as temp:
                real_market.LOCK_PATH = Path(temp) / "locked_subset.json"
                token = "unit-unlock"
                real_market.LOCK_PATH.write_text(json.dumps({
                    "unlock_token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest()
                }), encoding="utf-8")
                with self.assertRaises(PermissionError):
                    real_market._check_unlock("locked_test", None)
                real_market._check_unlock("locked_test", token)
                real_market._check_unlock("validation", None)
        finally:
            real_market.LOCK_PATH = original_lock_path

    def test_phase1e_multisymbol_training_normalization_and_hash(self) -> None:
        sample = pd.DataFrame({
            "datetime": pd.date_range("2025-01-01 09:15", periods=3, freq="5min", tz="Asia/Kolkata"),
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
        })
        first = normalize_raw_intraday(sample, symbol="RELIANCE.NS", exchange="NSE", source="unit")
        second = normalize_raw_intraday(sample, symbol="TCS.NS", exchange="NSE", source="unit")
        combined = pd.concat([first, second], ignore_index=True)
        self.assertEqual(validate_training_dataset(combined)["status"], "valid")
        self.assertEqual(training_hash(combined), training_hash(combined.sample(frac=1, random_state=7)))

    def test_phase1e_training_quality_detects_duplicates_and_malformed_ohlc(self) -> None:
        sample = normalize_raw_intraday(self.bars.head(3), symbol="SBIN.NS", exchange="NSE", source="unit")
        duplicated = pd.concat([sample, sample.head(1)], ignore_index=True)
        self.assertEqual(validate_training_dataset(duplicated)["status"], "error")
        bad = sample.copy()
        bad.loc[0, "high"] = bad.loc[0, "low"] - 1
        self.assertEqual(validate_training_dataset(bad)["status"], "error")

    def test_phase1e_leakage_guard_rejects_protected_period_overlap(self) -> None:
        protected = protected_evaluation_boundaries()
        boundary = pd.Timestamp(protected["splits"]["validation"]["start"])
        sample = pd.DataFrame({
            "timestamp": [boundary],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })
        normalized = normalize_raw_intraday(sample, symbol="RELIANCE.NS", exchange="NSE", source="unit")
        result = assert_training_dataset_safe(normalized, protected=protected)
        self.assertFalse(result["safe"])
        self.assertGreaterEqual(result["issue_count"], 1)

    def test_phase1e_cutoff_and_embargo_reject_new_training_rows(self) -> None:
        cutoff = training_cutoff_spec(lookback_bars=3, max_horizon_bars=2)
        sample = pd.DataFrame({
            "timestamp": [pd.Timestamp(cutoff["first_protected_timestamp"])],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })
        normalized = normalize_raw_intraday(sample, symbol="RELIANCE.NS", exchange="NSE", source="unit")
        self.assertFalse(assert_phase1e_training_cutoff(normalized, cutoff=cutoff)["safe"])

    def test_phase1e_kronos_schema_and_deterministic_windows(self) -> None:
        timestamps = pd.date_range("2026-01-05 09:15", periods=12, freq="5min", tz="Asia/Kolkata")
        sample = pd.DataFrame({
            "timestamp": timestamps,
            "open": [100 + index for index in range(12)],
            "high": [101 + index for index in range(12)],
            "low": [99 + index for index in range(12)],
            "close": [100.5 + index for index in range(12)],
            "volume": [1000 + index for index in range(12)],
        })
        normalized = normalize_raw_intraday(sample, symbol="UNIT.NS", exchange="NSE", source="unit")
        kronos_frame = to_kronos_training_frame(normalized)
        self.assertEqual(list(kronos_frame.columns), ["timestamps", "open", "high", "low", "close", "volume", "amount"])
        first = generate_kronos_training_windows(normalized, lookback_window=3, predict_window=2, stride_bars=2)
        second = generate_kronos_training_windows(normalized, lookback_window=3, predict_window=2, stride_bars=2)
        self.assertEqual(first["status"], "pass")
        self.assertEqual(first["window_count"], 4)
        self.assertEqual(first["windows"], second["windows"])

    def test_phase1e_kronos_window_generation_blocks_protected_data(self) -> None:
        protected = protected_evaluation_boundaries()
        boundary = pd.Timestamp(protected["splits"]["development"]["start"])
        timestamps = pd.date_range(boundary, periods=12, freq="5min")
        sample = pd.DataFrame({
            "timestamp": timestamps,
            "open": [100 + index for index in range(12)],
            "high": [101 + index for index in range(12)],
            "low": [99 + index for index in range(12)],
            "close": [100.5 + index for index in range(12)],
            "volume": [1000 + index for index in range(12)],
        })
        normalized = normalize_raw_intraday(sample, symbol="RELIANCE.NS", exchange="NSE", source="unit")
        result = generate_kronos_training_windows(normalized, lookback_window=3, predict_window=2)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["window_count"], 0)


    def test_phase1e_c2_resamples_complete_1m_bars_to_5m(self) -> None:
        timestamps = pd.date_range("2026-01-05 09:15", periods=10, freq="1min", tz="Asia/Kolkata")
        raw = pd.DataFrame({
            "time": [int(ts.timestamp()) for ts in timestamps],
            "open": [100 + index for index in range(10)],
            "high": [101 + index for index in range(10)],
            "low": [99 + index for index in range(10)],
            "close": [100.5 + index for index in range(10)],
            "Volume": [1000 + index for index in range(10)],
        })
        bars, report = resample_1m_to_5m(raw, symbol="RELIANCE.NS")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(bars), 2)
        self.assertEqual(float(bars.iloc[0]["open"]), 100.0)
        self.assertEqual(float(bars.iloc[0]["high"]), 105.0)
        self.assertEqual(float(bars.iloc[0]["low"]), 99.0)
        self.assertEqual(float(bars.iloc[0]["close"]), 104.5)
        self.assertEqual(float(bars.iloc[0]["volume"]), 5010.0)

    def test_phase1e_c2_rejects_partial_5m_bars_by_default(self) -> None:
        timestamps = pd.date_range("2026-01-05 09:15", periods=4, freq="1min", tz="Asia/Kolkata")
        raw = pd.DataFrame({
            "time": [int(ts.timestamp()) for ts in timestamps],
            "open": [100, 101, 102, 103],
            "high": [101, 102, 103, 104],
            "low": [99, 100, 101, 102],
            "close": [100.5, 101.5, 102.5, 103.5],
            "Volume": [1000, 1001, 1002, 1003],
        })
        bars, report = resample_1m_to_5m(raw, symbol="TCS.NS")
        self.assertEqual(len(bars), 0)
        self.assertIn("partial_4_of_5", report["rejected_reasons"])

    def test_phase1e_c2_source_audit_remains_yellow_without_data_license(self) -> None:
        audit = phase1e_c2_source_audit_metadata()
        self.assertEqual(audit["pinned_commit_sha"], "2c01a18c694f245556ff58bf7b882280f1de3679")
        self.assertIsNone(audit["repository_license"])
        self.assertEqual(audit["legal_provenance_status"], "uncertain")

    def test_phase2a_symbol_mapping_and_cache_key_are_deterministic(self) -> None:
        nse = canonical_instrument("RELIANCE", "NSE")
        bse = canonical_instrument("RELIANCE.BO", "NSE")
        self.assertEqual(nse.canonical_id, "NSE:RELIANCE")
        self.assertEqual(nse.provider_symbols["yahoo"], "RELIANCE.NS")
        self.assertEqual(bse.canonical_id, "BSE:RELIANCE")
        request = MarketDataRequest("RELIANCE", "NSE", start="2026-01-01", end="2026-01-31")
        self.assertEqual(provider_cache_key("yahoo", request, "1"), provider_cache_key("yahoo", request, "1"))

    def test_phase2a_provider_result_preserves_provenance_and_schema(self) -> None:
        request = MarketDataRequest("INFY", "NSE")
        bars = normalize_provider_bars(self.bars.head(5), provider="unit", request=request, retrieved_at="2026-01-01T00:00:00+00:00")
        result = ProviderResult("unit", request, bars, {"source": "mock"}, {"status": "valid"}, {"status": "HEALTHY"})
        manifest = result.as_manifest()
        self.assertEqual(manifest["provider"], "unit")
        self.assertEqual(manifest["row_count"], 5)
        self.assertEqual(bars.iloc[0]["symbol"], "INFY")
        self.assertIn("amount", bars.columns)

    def test_phase2a_fallback_uses_secondary_provider(self) -> None:
        class FailingProvider:
            name = "fail"
            def get_historical(self, request):
                raise RuntimeError("no data")
            def health_check(self):
                return {"status": "FAILED"}
        class WorkingProvider:
            name = "work"
            def get_historical(self, request):
                bars = normalize_provider_bars(self_bars.head(3), provider="work", request=request, retrieved_at="2026-01-01T00:00:00+00:00")
                return ProviderResult("work", request, bars, {}, {"status": "valid"}, {"status": "HEALTHY"})
            def health_check(self):
                return {"status": "HEALTHY"}
        self_bars = self.bars
        result = FallbackProvider([FailingProvider(), WorkingProvider()]).get_historical(MarketDataRequest("SBIN", "NSE"))
        self.assertEqual(result.provider, "work")
        self.assertEqual(result.provenance["fallback_chain"], ["fail", "work"])

    def test_phase2a_registry_and_artifacts(self) -> None:
        registry = ProviderRegistry()
        class MockProvider:
            name = "mock"
            def get_historical(self, request):
                raise NotImplementedError
            def health_check(self):
                return {"status": "UNKNOWN"}
        registry.register(MockProvider())
        self.assertEqual(registry.as_dict()["providers"], ["mock"])
        artifacts = phase2a_architecture_artifacts()
        self.assertIn("canonical_market_bar_schema", artifacts)
        self.assertIn("cache_specification", artifacts)


if __name__ == "__main__":
    unittest.main()
