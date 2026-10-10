"""Offline Phase 8 tests for deterministic evidence fusion."""

from __future__ import annotations

import copy
import http.client
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

from app.evidence_fusion import EvidenceFusionEngine, FUSION_VERSION
from app.evidence_snapshot import SCHEMA_VERSION, snapshot_id


NOW = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def evidence_record(*, forecast: str | None = "up", technical: str | None = "bullish",
                    news: str | None = "positive", stale: bool = False,
                    forecast_change: float = 3.0, technical_strength: float = 0.8,
                    market_quality: str = "PASS") -> dict:
    observed = NOW - timedelta(days=10) if stale else NOW - timedelta(minutes=5)
    content = {
        "schema_version": SCHEMA_VERSION,
        "instrument": {"canonical_symbol": "NSE:TESTCO", "provider_symbol": "TESTCO.NS", "exchange": "NSE"},
        "market_data": {"input_sha256": "a" * 64, "capture_id": "capture", "bronze_sha256": "b" * 64,
                        "silver_sha256": "c" * 64, "provider": "yahoo", "retrieved_at": observed.isoformat(),
                        "quality": market_quality, "cache_status": "hit"},
        "kronos": {},
        "technicals": {},
        "news": {},
        "research_view": {"direction": "NO_STRONG_EDGE", "confidence": {"value": None,
                          "scale": "0_to_1", "calibrated": False, "qualitative_label": "LOW"}},
    }
    if forecast is not None:
        content["kronos"] = {"model_id": "NeoQuasar/Kronos-base", "forecast_fingerprint": "d" * 64,
                             "forecast_sha256": "e" * 64, "direction": forecast,
                             "forecast_pct_change": forecast_change,
                             "config": {"input_rows": 256, "forecast_rows": 75}}
    if technical is not None:
        signal = "bullish" if technical == "bullish" else "bearish" if technical == "bearish" else "neutral"
        content["technicals"] = {"evidence_reference": "f" * 64, "as_of": observed.isoformat(),
                                 "trend": technical, "regime": "TRENDING_BULL" if technical == "bullish"
                                 else "TRENDING_BEAR" if technical == "bearish" else "SIDEWAYS",
                                 "version": "phase3_test", "values": [
                                     {"indicator": "EMA50", "value": 100, "signal": signal,
                                      "strength": technical_strength, "reason": "Synthetic test signal."}]}
    if news is not None:
        score = 0.6 if news == "positive" else -0.6 if news == "negative" else 0.0
        direction = "POSITIVE" if score > 0 else "NEGATIVE" if score < 0 else "NEUTRAL"
        content["news"] = {"provider": "offline", "providers_used": ["offline"],
                           "retrieved_at": observed.isoformat(), "cache_status": "hit",
                           "gold_sha256": "1" * 64, "evidence_sha256": "2" * 64,
                           "evidence_status": "GOLD_AVAILABLE", "impact_score": score,
                           "formula_version": "news_impact_v1", "uncertainty": [],
                           "article_evidence": [{"id": "story", "title": "Synthetic evidence"}],
                           "impact_evidence": [{"event_id": "event", "direction": direction,
                                                "impact": score, "headline": "Synthetic evidence"}],
                           "source_urls": ["https://example.test/story"]}
    return {"snapshot_id": snapshot_id(content), "created_at": observed.isoformat(), "evidence": content}


def claim(text: str, ids: list[str]) -> dict:
    return {"text": text, "claim_type": "INTERPRETATION", "support_type": "INTERPRETIVE",
            "evidence_type": "MULTI_SOURCE", "evidence_ids": ids, "confidence": 0.95, "material": True}


def agent_result(record: dict, *, risk: str = "LOW", bull: bool = True, bear: bool = True) -> dict:
    digest = record["snapshot_id"]
    agents = {}
    if bull:
        agents["bull"] = {"status": "CACHED", "cached": True, "analyzed_at": NOW.isoformat(),
                          "report": {"agent_type": "bull", "snapshot_id": digest, "stance": "BULL_CASE",
                                     "argument": claim("The forecast may support an upside case.", ["kronos.direction"]),
                                     "key_factors": [], "limitations": [], "uncertainty": []}}
    if bear:
        agents["bear"] = {"status": "CACHED", "cached": True, "analyzed_at": NOW.isoformat(),
                          "report": {"agent_type": "bear", "snapshot_id": digest, "stance": "BEAR_CASE",
                                     "argument": claim("The same evidence may support a downside case.", ["kronos.direction"]),
                                     "key_factors": [], "limitations": [], "uncertainty": []}}
    agents["risk"] = {"status": "CACHED", "cached": True, "analyzed_at": NOW.isoformat(),
                      "report": {"agent_type": "risk", "snapshot_id": digest, "risk_level": risk,
                                 "confidence_in_risk_assessment": 0.9,
                                 "risk_factors": [claim("The forecast may not match the realized path.",
                                                        ["kronos.direction"])],
                                 "conflicts": [], "model_risks": [], "data_risks": [],
                                 "event_risks": [], "missing_evidence": [], "limitations": [], "uncertainty": []}}
    return {"snapshot_id": digest, "status": "CACHED", "agents": agents}


def pipeline(*, failed: bool = False) -> dict:
    status = "FAILED" if failed else "HEALTHY"
    return {"schema_version": "capstone_pipeline_v1", "updated_at": NOW.isoformat(),
            "stages": {"source": {"status": status}, "silver": {"status": status},
                       "gold": {"status": "HEALTHY"}}}


class FusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = EvidenceFusionEngine(Path(self.temp.name))

    def fuse(self, record: dict, *, agents: dict | None = None, failed_pipeline: bool = False) -> dict:
        return self.engine.fuse(record, agent_result=agents, pipeline=pipeline(failed=failed_pipeline), as_of=NOW)

    def test_case_01_everything_bullish(self) -> None:
        record = evidence_record()
        result = self.fuse(record, agents=agent_result(record, bear=False))
        self.assertEqual(result["view"], "STRONGLY_BULLISH")
        self.assertEqual(result["support_level"], "HIGH")
        self.assertTrue(result["agreements"])

    def test_case_02_everything_bearish(self) -> None:
        record = evidence_record(forecast="down", technical="bearish", news="negative")
        result = self.fuse(record, agents=agent_result(record, bull=False))
        self.assertEqual(result["view"], "STRONGLY_BEARISH")

    def test_case_03_kronos_bullish_technicals_bearish(self) -> None:
        record = evidence_record(technical="bearish", news=None)
        result = self.fuse(record)
        self.assertEqual(result["view"], "MIXED")
        self.assertTrue(any(row["conflict_type"] == "PRIMARY_DIRECTION_CONFLICT" for row in result["conflicts"]))

    def test_case_04_kronos_bullish_negative_news(self) -> None:
        record = evidence_record(news="negative")
        result = self.fuse(record)
        self.assertTrue(result["conflicts"])
        self.assertTrue(any(row["evidence_id"] == "news.impact_score" for row in result["opposing_evidence"]))

    def test_case_05_bull_and_bear_agents_disagree(self) -> None:
        record = evidence_record()
        result = self.fuse(record, agents=agent_result(record))
        self.assertTrue(any(row["conflict_type"] == "AGENT_INTERPRETATION_CONFLICT" for row in result["conflicts"]))
        self.assertEqual(result["view"], "STRONGLY_BULLISH")

    def test_case_06_high_risk_reduces_support_not_direction(self) -> None:
        record = evidence_record()
        result = self.fuse(record, agents=agent_result(record, risk="HIGH", bear=False))
        self.assertEqual(result["view"], "STRONGLY_BULLISH")
        self.assertEqual(result["support_level"], "LOW")

    def test_case_07_news_missing_is_explicit(self) -> None:
        record = evidence_record(news=None)
        result = self.fuse(record)
        self.assertIn("NEWS_INTELLIGENCE", result["missing_evidence"])
        self.assertNotIn("news.impact_score", result["aggregation"]["eligible_primary_sources"])

    def test_case_08_kronos_missing_can_use_other_primary_sources(self) -> None:
        record = evidence_record(forecast=None)
        result = self.fuse(record)
        self.assertIn("KRONOS_FORECAST", result["missing_evidence"])
        self.assertIn(result["view"], {"BULLISH", "STRONGLY_BULLISH"})

    def test_case_09_stale_evidence_abstains(self) -> None:
        record = evidence_record(stale=True)
        result = self.fuse(record)
        self.assertEqual(result["view"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["aggregation"]["eligible_primary_sources"], [])

    def test_case_10_confident_agents_cannot_amplify_weak_primary_evidence(self) -> None:
        record = evidence_record(news=None, forecast_change=0.1, technical_strength=0.05)
        without_agents = self.fuse(record)
        with_agents = self.fuse(record, agents=agent_result(record, bear=False))
        self.assertEqual(with_agents["view"], without_agents["view"])
        self.assertEqual(with_agents["aggregation"]["internal_direction_score"],
                         without_agents["aggregation"]["internal_direction_score"])

    def test_case_11_pipeline_failure_is_meta_evidence(self) -> None:
        record = evidence_record()
        healthy = self.fuse(record, agents=agent_result(record, bear=False))
        failed = self.fuse(record, agents=agent_result(record, bear=False), failed_pipeline=True)
        self.assertEqual(failed["view"], healthy["view"])
        self.assertEqual(failed["support_level"], "LOW")
        self.assertTrue(any("pipeline" in row["text"].lower() for row in failed["risks"]))

    def test_case_12_insufficient_primary_evidence_abstains(self) -> None:
        record = evidence_record(forecast=None, technical=None, news=None)
        result = self.fuse(record, agents=agent_result(record))
        self.assertEqual(result["view"], "INSUFFICIENT_EVIDENCE")

    def test_case_13_derived_lineage_is_deduplicated(self) -> None:
        record = evidence_record()
        result = self.fuse(record, agents=agent_result(record))
        derived = [row for row in result["evidence_items"] if row["role"] == "DERIVED"]
        self.assertTrue(derived)
        self.assertTrue(all(not row["contributes_to_direction"] for row in derived))
        self.assertTrue(any(row["evidence_id"] == "agent.bull" for row in result["deduplication"]))

    def test_case_14_agent_repetition_does_not_double_count_kronos(self) -> None:
        record = evidence_record(news=None)
        first = self.fuse(record)
        second = self.fuse(record, agents=agent_result(record, bull=True, bear=False))
        self.assertEqual(first["aggregation"]["internal_direction_score"],
                         second["aggregation"]["internal_direction_score"])
        self.assertEqual(first["aggregation"]["eligible_primary_sources"],
                         second["aggregation"]["eligible_primary_sources"])

    def test_case_15_contradictory_primary_sources_are_visible(self) -> None:
        record = evidence_record(technical="bearish", news="negative")
        result = self.fuse(record)
        conflict_ids = {item for row in result["conflicts"] for item in row["evidence_ids"]}
        self.assertIn("kronos.direction", conflict_ids)
        self.assertIn("technicals.trend", conflict_ids)

    def test_missing_is_not_encoded_as_neutral(self) -> None:
        result = self.fuse(evidence_record(news=None))
        self.assertFalse(any(row["evidence_type"] == "NEWS" for row in result["evidence_items"]))
        self.assertIn("NEWS_INTELLIGENCE", result["missing_evidence"])

    def test_contract_provenance_and_confidence_semantics(self) -> None:
        record = evidence_record()
        result = self.fuse(record, agents=agent_result(record))
        self.assertEqual(result["fusion_version"], FUSION_VERSION)
        self.assertEqual(result["schema_version"], "fusion_output_v1")
        self.assertTrue(all(row["provenance"] is not None for row in result["source_lineage"]))
        self.assertTrue(all(row["confidence_semantics"].endswith("NOT_PROBABILITY")
                            for row in result["evidence_items"]))
        self.assertNotIn("BUY", json.dumps(result).upper())
        self.assertNotIn("SELL", json.dumps(result).upper())

    def test_cache_identity_changes_with_upstream_evidence(self) -> None:
        record = evidence_record()
        agents = agent_result(record, bear=False)
        first = self.fuse(record, agents=agents)
        second = self.fuse(record, agents=agents)
        changed = copy.deepcopy(agents)
        changed["agents"]["risk"]["report"]["risk_level"] = "HIGH"
        third = self.fuse(record, agents=changed)
        self.assertEqual(first["cache_status"], "miss")
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(third["cache_status"], "miss")

    def test_ledger_and_health_are_durable(self) -> None:
        record = evidence_record()
        result = self.fuse(record)
        ledger = json.loads((Path(self.temp.name) / "runs" / f"{result['fusion_run_id']}.json").read_text())
        self.assertEqual(ledger["result_hash"], result["result_hash"])
        self.assertEqual(self.engine.health()["status"], "STALE")

    def test_inputs_remain_byte_identical(self) -> None:
        record = evidence_record()
        agents = agent_result(record)
        record_before = json.dumps(record, sort_keys=True)
        agents_before = json.dumps(agents, sort_keys=True)
        self.fuse(record, agents=agents)
        self.assertEqual(json.dumps(record, sort_keys=True), record_before)
        self.assertEqual(json.dumps(agents, sort_keys=True), agents_before)

    def test_fusion_route_is_authenticated_read_only_orchestration(self) -> None:
        from app import server
        record = evidence_record()
        fused = self.fuse(record)
        team = type("Team", (), {"result": lambda self, value: {"snapshot_id": value["snapshot_id"], "agents": {}},
                                  "health": lambda self, record=None: {"status": "READY"}})()
        product = type("Pipeline", (), {"snapshot": lambda self: pipeline()})()
        news = type("News", (), {"pipeline_stage": lambda self: {"status": "HEALTHY"}})()
        engine = type("Fusion", (), {"fuse": lambda self, *args, **kwargs: fused,
                                     "health": lambda self: {"status": "HEALTHY"}})()
        with patch.object(server, "current_agent_snapshot", return_value=record), \
             patch.object(server, "AGENT_TEAM", team), patch.object(server, "PRODUCT_PIPELINE", product), \
             patch.object(server, "NEWS_SERVICE", news), patch.object(server, "FUSION_ENGINE", engine):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.DashboardHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            headers = {"Host": f"127.0.0.1:{httpd.server_port}", "X-Kronos-Request": "dashboard",
                       "Sec-Fetch-Site": "same-origin"}
            connection.request("GET", "/api/fusion?id=" + record["snapshot_id"], headers=headers)
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(body["fusion_version"], FUSION_VERSION)

    def test_dashboard_contains_explainable_fusion_surface(self) -> None:
        root = Path(__file__).resolve().parents[2]
        html = (root / "app" / "dashboard.html").read_text(encoding="utf-8")
        script = (root / "app" / "dashboard.js").read_text(encoding="utf-8")
        for expected in ("fusion-section", "fusion-supporting", "fusion-opposing", "fusion-risks",
                         "fusion-missing", 'data-stage="fusion"'):
            self.assertIn(expected, html)
        self.assertIn("/api/fusion?id=", script)
        self.assertIn("Support is qualitative", html)


if __name__ == "__main__":
    unittest.main()
