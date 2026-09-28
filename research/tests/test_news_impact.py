"""Phase 6.2 news impact tests use synthetic evidence and no network calls."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.news_impact import analyze_article, assess_news, research_outlook, save_gold
from app.product_pipeline import ProductPipeline


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
SYMBOL = "TCS.NS"
COMPANY = "Tata Consultancy Services Limited"


def article(title: str, *, hours: int = 2, source_quality: str = "high", summary: str = "",
            identifier: str = "a", url: str | None = None, published: bool = True) -> dict:
    return {"id": identifier, "symbol": SYMBOL, "title": title, "summary": summary,
            "url": url or f"https://example.com/{identifier}", "source": "Example Business",
            "source_quality": source_quality, "event_type": "other",
            "published_at": (NOW - timedelta(hours=hours)).isoformat() if published else None,
            "retrieved_at": NOW.isoformat(), "provenance": {"provider": "Tavily", "bronze_sha256": "raw-hash"}}


def payload(*events: dict, status: str = "FRESH") -> dict:
    return {"symbol": SYMBOL, "status": status, "events": list(events)}


class NewsImpactTests(unittest.TestCase):
    def test_positive_contract_headline(self) -> None:
        event = article("Tata Consultancy Services wins major contract")
        result = assess_news(payload(event), COMPANY, as_of=NOW)
        self.assertEqual(result["status"], "POSITIVE")
        self.assertGreater(result["score"], 0)
        self.assertAlmostEqual(result["score"], result["events"][0]["impact"], delta=0.01)
        self.assertEqual(result["articles"][0]["event_type"], "ORDER_WIN")
        self.assertEqual(result["articles"][0]["provenance"]["bronze_sha256"], "raw-hash")

    def test_negative_guidance_headline(self) -> None:
        event = article("TCS cuts guidance", summary="Tata Consultancy Services changed its outlook")
        result = assess_news(payload(event), COMPANY, as_of=NOW)
        self.assertEqual(result["status"], "NEGATIVE")
        self.assertLess(result["score"], 0)
        self.assertAlmostEqual(result["score"], result["events"][0]["impact"], delta=0.01)
        self.assertEqual(result["articles"][0]["event_type"], "GUIDANCE")

    def test_neutral_article_does_not_move_view(self) -> None:
        event = article("Tata Consultancy Services launches a laboratory")
        result = assess_news(payload(event), COMPANY, as_of=NOW)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_ticker_mention_without_company_context_is_insufficient(self) -> None:
        event = article("TCS wins contract")
        analyzed = analyze_article(event, COMPANY, NOW)
        self.assertIn("LOW_RELEVANCE", analyzed["flags"])
        self.assertEqual(analyzed["impact"], 0)

    def test_wrong_symbol_in_cached_article_cannot_influence_view(self) -> None:
        wrong = article("Tata Consultancy Services wins contract")
        wrong["symbol"] = "INFY.NS"
        result = assess_news(payload(wrong), COMPANY, as_of=NOW)
        self.assertEqual(result["score"], 0)
        self.assertIn("SYMBOL_MISMATCH", result["articles"][0]["flags"])

    def test_old_and_unknown_timestamp_are_excluded(self) -> None:
        old = article("Tata Consultancy Services wins contract", hours=200)
        unknown = article("Tata Consultancy Services wins contract", published=False)
        self.assertEqual(analyze_article(old, COMPANY, NOW)["impact"], 0)
        self.assertEqual(analyze_article(unknown, COMPANY, NOW)["impact"], 0)
        self.assertIn("TIMESTAMP_UNCERTAIN", analyze_article(unknown, COMPANY, NOW)["flags"])

    def test_future_timestamp_is_excluded(self) -> None:
        future = article("Tata Consultancy Services wins contract", hours=-2)
        self.assertEqual(analyze_article(future, COMPANY, NOW)["impact"], 0)

    def test_unrated_source_is_weaker_than_curated_source(self) -> None:
        title = "Tata Consultancy Services wins contract"
        high = analyze_article(article(title), COMPANY, NOW)
        unknown = analyze_article(article(title, source_quality="unrated"), COMPANY, NOW)
        self.assertGreater(high["impact"], unknown["impact"])
        self.assertEqual(unknown["source_quality"], "UNKNOWN")
        medium = analyze_article(article(title, source_quality="medium"), COMPANY, NOW)
        low = analyze_article(article(title, source_quality="low"), COMPANY, NOW)
        self.assertGreater(high["impact"], medium["impact"])
        self.assertGreater(medium["impact"], low["impact"])
        self.assertIn("SOURCE_LOW", low["flags"])

    def test_conflicting_events_are_mixed_and_bounded(self) -> None:
        good = article("Tata Consultancy Services wins contract", identifier="good")
        bad = article("Tata Consultancy Services cuts guidance", identifier="bad")
        result = assess_news(payload(good, bad), COMPANY, as_of=NOW)
        self.assertEqual(result["status"], "MIXED")
        self.assertGreater(result["positive_strength"], 0)
        self.assertGreater(result["negative_strength"], 0)
        self.assertLessEqual(abs(result["score"]), 1)

    def test_duplicate_coverage_is_one_event_not_two_votes(self) -> None:
        first = article("Tata Consultancy Services wins major contract", identifier="one")
        second = article("Tata Consultancy Services wins major contract", identifier="two",
                         url="https://other.example.com/two")
        single = assess_news(payload(first), COMPANY, as_of=NOW)
        double = assess_news(payload(first, second), COMPANY, as_of=NOW)
        self.assertEqual(double["events_processed"], 1)
        self.assertEqual(double["score"], single["score"])
        self.assertEqual(len(double["events"][0]["article_ids"]), 2)

    def test_no_news_has_no_influence(self) -> None:
        impact = assess_news(payload(status="NO_EVIDENCE"), COMPANY, as_of=NOW)
        outlook = research_outlook("up", {"trend": "bullish", "regime": "TRENDING_BULL"}, impact)
        self.assertEqual(impact["score"], 0)
        self.assertEqual(outlook["baseline_view"], outlook["preliminary_research_view"])
        self.assertEqual(outlook["confidence_change"], "UNCHANGED")

    def test_missing_matching_technicals_abstains(self) -> None:
        impact = assess_news(payload(), COMPANY, as_of=NOW)
        outlook = research_outlook("up", None, impact)
        self.assertEqual(outlook["raw_kronos_view"], "BULLISH")
        self.assertEqual(outlook["preliminary_research_view"], "NO_STRONG_EDGE")

    def test_stale_news_cannot_influence_view(self) -> None:
        result = assess_news(payload(article("Tata Consultancy Services cuts guidance"), status="STALE"),
                             COMPANY, as_of=NOW)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        mixed = assess_news(payload(article("Tata Consultancy Services wins contract", identifier="one"),
                                    article("Tata Consultancy Services cuts guidance", identifier="two"),
                                    status="STALE"), COMPANY, as_of=NOW)
        self.assertFalse(mixed["conflict"])
        self.assertEqual(mixed["status"], "INSUFFICIENT_EVIDENCE")

    def test_opposing_news_downgrades_without_reversing_kronos(self) -> None:
        impact = assess_news(payload(article("Tata Consultancy Services cuts guidance")), COMPANY, as_of=NOW)
        outlook = research_outlook("up", {"trend": "bullish", "regime": "TRENDING_BULL"}, impact)
        self.assertEqual(outlook["raw_kronos_view"], "BULLISH")
        self.assertEqual(outlook["preliminary_research_view"], "NO_STRONG_EDGE")
        self.assertEqual(outlook["confidence_change"], "LOWER")
        self.assertNotIn("BEARISH", outlook["preliminary_research_view"])

    def test_supportive_news_never_creates_probability(self) -> None:
        impact = assess_news(payload(article("Tata Consultancy Services wins contract")), COMPANY, as_of=NOW)
        outlook = research_outlook("up", {"trend": "bullish", "regime": "TRENDING_BULL"}, impact)
        self.assertEqual(outlook["preliminary_research_view"], "MODERATELY_BULLISH")
        self.assertEqual(outlook["confidence"], "MODERATE")
        self.assertIn("not a calibrated probability", outlook["confidence_basis"])

    def test_technical_conflict_abstains(self) -> None:
        impact = assess_news(payload(), COMPANY, as_of=NOW)
        outlook = research_outlook("up", {"trend": "bearish", "regime": "SIDEWAYS"}, impact)
        self.assertEqual(outlook["preliminary_research_view"], "NO_STRONG_EDGE")

    def test_expired_saved_forecast_has_no_current_research_edge(self) -> None:
        impact = assess_news(payload(article("Tata Consultancy Services wins contract")), COMPANY, as_of=NOW)
        outlook = research_outlook("up", {"trend": "bullish"}, impact,
                                   forecast_ends_at=(NOW - timedelta(minutes=6)).isoformat(), as_of=NOW)
        self.assertEqual(outlook["status"], "EXPIRED_FORECAST")
        self.assertEqual(outlook["preliminary_research_view"], "NO_STRONG_EDGE")
        self.assertEqual(outlook["confidence_change"], "UNAVAILABLE")

    def test_gold_artifact_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            impact = assess_news(payload(article("Tata Consultancy Services wins contract")), COMPANY, as_of=NOW)
            outlook = research_outlook("up", None, impact)
            first = save_gold(Path(folder), SYMBOL, impact, outlook)
            second = save_gold(Path(folder), SYMBOL, impact, outlook)
            self.assertEqual(first, second)
            content = (Path(folder) / first["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), first["sha256"])

    def test_gold_technicals_require_symbol_fingerprint_and_hash_match(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            gold = {"technicals": {"trend": "bullish"}, "kronos_output": {"summary_fingerprint": "right"}}
            content = json.dumps(gold).encode()
            (root / "gold").mkdir()
            (root / "gold" / "match.json").write_bytes(content)
            manifest = {"symbol": SYMBOL, "gold": {"path": "gold/match.json", "sha256": hashlib.sha256(content).hexdigest()}}
            (root / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")
            pipeline = ProductPipeline(root)
            self.assertEqual(pipeline.matching_technicals(SYMBOL, "right"), {"trend": "bullish"})
            self.assertIsNone(pipeline.matching_technicals(SYMBOL, "wrong"))
            self.assertIsNone(pipeline.matching_technicals("INFY.NS", "right"))
            (root / "gold" / "match.json").write_text("changed", encoding="utf-8")
            self.assertIsNone(pipeline.matching_technicals(SYMBOL, "right"))

    def test_server_adds_outlook_only_for_matching_saved_symbol(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
        from app import server
        news = {"symbol": SYMBOL, "status": "FRESH", "events": [article("Tata Consultancy Services wins contract")],
                "news_pipeline": {}}
        with (patch.object(server.NEWS_SERVICE, "get", return_value=news),
              patch.object(server.NEWS_SERVICE, "official_name", return_value=COMPANY),
              patch.object(server, "load_summary", return_value={"input_source": "INFY.NS live 5-minute data", "direction": "up"}),
              patch.object(server.NEWS_SERVICE, "record_impact")):
            result = server.build_news_research_payload(SYMBOL)
        self.assertIn("news_impact", result)
        self.assertNotIn("research_outlook", result)

    def test_server_matching_saved_forecast_keeps_raw_summary_intact(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
        from app import server
        summary = {"input_source": "TCS.NS live 5-minute data", "direction": "up", "forecast_final_close": 100.0}
        news = {"symbol": SYMBOL, "status": "FRESH", "events": [article("Tata Consultancy Services cuts guidance")],
                "news_pipeline": {}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path, forecast_path = root / "input.csv", root / "forecast.csv"
            input_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-25T15:15:00+05:30,100,101,99,100,10,1000\n", encoding="utf-8")
            forecast_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-28T09:15:00+05:30,101,102,100,101,10,1010\n", encoding="utf-8")
            manifest_path = root / "latest.json"
            manifest_path.write_text(json.dumps({"symbol": SYMBOL}), encoding="utf-8")
            with (patch.object(server.NEWS_SERVICE, "get", return_value=news),
              patch.object(server.NEWS_SERVICE, "official_name", return_value=COMPANY),
              patch.object(server.NEWS_SERVICE, "record_impact"),
              patch.object(server, "assess_news", side_effect=lambda data, name: assess_news(data, name, as_of=NOW)),
              patch.object(server, "load_summary", return_value=summary),
              patch.object(server, "summary_fingerprint", return_value="saved-fingerprint"),
              patch.object(server.PRODUCT_PIPELINE, "matching_technicals",
                           return_value={"trend": "bullish", "regime": "TRENDING_BULL", "as_of": NOW.isoformat()}),
              patch.object(server.PRODUCT_PIPELINE, "_latest", manifest_path),
              patch.object(server, "UPLOADED_DATA_PATH", input_path),
              patch.object(server, "FORECAST_PATH", forecast_path),
              patch.object(server, "EVIDENCE_DIR", root / "snapshots"),
              patch.object(server, "save_gold", return_value={"sha256": "gold-hash"})):
                result = server.build_news_research_payload(SYMBOL)
        self.assertEqual(result["research_outlook"]["preliminary_research_view"], "NO_STRONG_EDGE")
        self.assertIn("evidence_snapshot_id", result)
        self.assertEqual(result["news_pipeline"]["gold"]["sha256"], "gold-hash")
        self.assertEqual(summary["forecast_final_close"], 100.0)


if __name__ == "__main__":
    unittest.main()
