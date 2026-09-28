"""News evidence tests use source-shaped fixtures and make no network calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.news_intelligence import GoogleNewsRssProvider, NewsService, TavilyNewsProvider, normalize_article


def article(title: str, suffix: str = "one", *, days_old: int = 1, summary: str = "") -> dict:
    return {"id": suffix, "content": {"id": suffix, "title": title,
            "canonicalUrl": {"url": f"https://example.com/{suffix}"},
            "pubDate": (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(),
            "summary": summary, "provider": {"displayName": "Example Publisher"}}}


def tavily_result(title: str = "Reliance Industries reports quarterly results", *,
                  url: str = "https://www.reuters.com/world/india/reliance-results", dated: bool = True) -> dict:
    result = {"title": title, "url": url, "content": "Reliance Industries reported quarterly results.", "score": 0.84}
    if dated:
        result["published_date"] = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    return result


class Response:
    def __init__(self, results: list[dict]):
        self.payload = json.dumps({"results": results, "usage": {"credits": 1}}).encode()

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, _limit): return self.payload


class FakeProvider:
    name = "mock news"

    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.calls = 0
        self.fail = False

    def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict]:
        self.calls += 1
        if self.fail:
            raise TimeoutError("provider unavailable")
        return self.items


class NewsIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_normalization_is_source_linked_and_conservative(self) -> None:
        item = article("Reliance Industries profit rises after quarterly results", summary="Reliance Industries reported results.")
        normalized = normalize_article(item, "RELIANCE.NS", "Reliance Industries Limited", datetime.now(timezone.utc), "mock news")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["event_type"], "earnings")
        self.assertEqual(normalized["sentiment"], "positive_cue")
        self.assertEqual(normalized["source"], "Example Publisher")
        self.assertEqual(normalized["url"], "https://example.com/one")
        self.assertEqual(normalized["provenance"]["relevance_basis"], "official company name in headline")

    def test_rejects_foreign_unrelated_old_and_unlinked_items(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertIsNone(normalize_article(article("Reliance (NYSE:RS) profit rises"), "RELIANCE.NS", "Reliance Industries Limited", now, "mock"))
        self.assertIsNone(normalize_article(article("Oil refiners in focus"), "RELIANCE.NS", "Reliance Industries Limited", now, "mock"))
        self.assertIsNone(normalize_article(article("Reliance Industries reports results", days_old=30), "RELIANCE.NS", "Reliance Industries Limited", now, "mock"))
        unsafe = article("Reliance Industries reports results")
        unsafe["content"]["canonicalUrl"] = {"url": "javascript:alert(1)"}
        self.assertIsNone(normalize_article(unsafe, "RELIANCE.NS", "Reliance Industries Limited", now, "mock"))
        repost = article("Reliance Industries reports results")
        repost["content"]["provider"]["displayName"] = "LinkedIn"
        self.assertIsNone(normalize_article(repost, "RELIANCE.NS", "Reliance Industries Limited", now, "mock"))

    def test_cache_and_positive_negative_counts(self) -> None:
        provider = FakeProvider([article("Reliance Industries profit rises", "up"),
                                 article("Reliance Industries cuts guidance", "down")])
        service = NewsService(self.root, provider)
        first = service.get("reliance.ns", company_hint="Reliance Industries Limited")
        second = service.get("RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(first["status"], "FRESH")
        self.assertEqual(len(first["events"]), 2)
        self.assertEqual(len(first["positive_evidence"]), 1)
        self.assertEqual(len(first["negative_evidence"]), 1)
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(service.get("RELIANCE.NS", refresh=True)["cache_status"], "hit")

    def test_no_evidence_and_provider_failure_are_honest(self) -> None:
        provider = FakeProvider([article("Oil refiners in focus")])
        service = NewsService(self.root, provider)
        empty = service.get("RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(empty["status"], "NO_EVIDENCE")
        self.assertEqual(empty["message"], "No verified recent evidence.")
        target = service._cache_path("RELIANCE.NS", "Reliance Industries Limited")
        cached = json.loads(target.read_text(encoding="utf-8"))
        cached["retrieved_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        target.write_text(json.dumps(cached), encoding="utf-8")
        provider.fail = True
        self.assertEqual(service.get("RELIANCE.NS")["status"], "STALE")
        with self.assertRaises(ValueError):
            service.get("../../secrets")

    def test_failure_without_cache_is_negative_cached(self) -> None:
        provider = FakeProvider()
        provider.fail = True
        service = NewsService(self.root, provider)
        first = service.get("TCS.NS")
        second = service.get("TCS.NS")
        self.assertEqual(first["status"], "UNAVAILABLE")
        self.assertEqual(first["message"], "No verified recent evidence.")
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(provider.calls, 1)

    def test_rss_fallback_preserves_publisher_and_provenance(self) -> None:
        class RssFixture:
            name = "Google News RSS"

            def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict]:
                return [article("HDFC Bank launches digital rupee payments", "rss")]

        service = NewsService(self.root, FakeProvider([]), RssFixture())
        result = service.get("HDFCBANK.NS", company_hint="HDFC Bank Limited")
        self.assertEqual(result["status"], "FRESH")
        self.assertEqual(result["provider"], "Google News RSS")
        self.assertEqual(result["events"][0]["event_type"], "product")
        self.assertEqual(result["events"][0]["source"], "Example Publisher")
        self.assertEqual(result["events"][0]["provenance"]["provider"], "Google News RSS")

    def test_rss_parser_uses_publisher_and_skips_malformed_date(self) -> None:
        published = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        feed = ("<rss><channel><item><title>HDFC Bank launches payments - Example Publisher</title>"
                "<link>https://news.google.com/rss/articles/one</link><source>Example Publisher</source>"
                f"<pubDate>{published}</pubDate></item><item><title>Bad date</title>"
                "<pubDate>not a date</pubDate></item></channel></rss>").encode()

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return feed

        with patch("app.news_intelligence.urlopen", return_value=Response()):
            items = GoogleNewsRssProvider().fetch("HDFCBANK.NS", 10, "HDFC Bank Limited")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content"]["title"], "HDFC Bank launches payments")
        self.assertEqual(items[0]["content"]["provider"]["displayName"], "Example Publisher")

    def test_tavily_basic_request_normalization_and_bronze(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        with patch("app.news_intelligence.urlopen", return_value=Response([tavily_result()])) as call:
            rows = tavily.fetch("RELIANCE.NS", 5, "Reliance Industries Limited")
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["topic"], "news")
        self.assertEqual(body["search_depth"], "basic")
        self.assertEqual(body["max_results"], 5)
        self.assertTrue(body["include_published_date"])
        self.assertIn("Reliance Industries", body["query"])
        normalized = normalize_article(rows[0], "RELIANCE.NS", "Reliance Industries Limited",
                                       datetime.now(timezone.utc), "Tavily")
        self.assertEqual(normalized["source_quality"], "high")
        self.assertEqual(normalized["url"], "https://www.reuters.com/world/india/reliance-results")
        self.assertEqual(normalized["provenance"]["query"], body["query"])
        self.assertEqual(len(list((self.root / "bronze").glob("*.json"))), 1)
        self.assertNotIn("fixture-key", next((self.root / "bronze").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(tavily.health()["credits"], 1)

    def test_tavily_missing_key_uses_yahoo_without_network(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "")
        yahoo = FakeProvider([article("Reliance Industries reports results")])
        service = NewsService(self.root, yahoo, tavily_provider=tavily)
        with patch("app.news_intelligence.urlopen") as call:
            result = service.get("RELIANCE.NS", company_hint="Reliance Industries Limited")
        call.assert_not_called()
        self.assertEqual(result["provider"], "mock news")
        self.assertEqual(result["tavily_health"]["status"], "UNAVAILABLE")
        self.assertEqual(service.pipeline_stage()["rows"], 0)

    def test_tavily_query_cache_avoids_second_request(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        with patch("app.news_intelligence.urlopen", return_value=Response([tavily_result()])) as call:
            tavily.fetch("RELIANCE.NS", 5, "Reliance Industries Limited")
            tavily.fetch("RELIANCE.NS", 5, "Reliance Industries Limited")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(tavily.health()["requests"], 1)

    def test_tavily_empty_falls_back_to_yahoo_then_rss(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        yahoo = FakeProvider([])
        class RssFixture:
            name = "Google News RSS"
            def fetch(self, symbol, count, company_name=""):
                return [article("Reliance Industries launches payments")]
        with patch("app.news_intelligence.urlopen", return_value=Response([])):
            result = NewsService(self.root, yahoo, RssFixture(), tavily).get(
                "RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(yahoo.calls, 1)
        self.assertEqual(result["provider"], "Google News RSS")
        self.assertEqual(len(result["events"]), 1)

    def test_tavily_empty_uses_yahoo_before_rss(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        yahoo = FakeProvider([article("Reliance Industries reports results")])
        class RssFixture:
            name = "Google News RSS"
            calls = 0
            def fetch(self, symbol, count, company_name=""):
                self.calls += 1
                return []
        rss = RssFixture()
        with patch("app.news_intelligence.urlopen", return_value=Response([])):
            result = NewsService(self.root, yahoo, rss, tavily).get(
                "RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(result["provider"], "mock news")
        self.assertEqual(yahoo.calls, 1)
        self.assertEqual(rss.calls, 1)

    def test_tavily_five_results_need_no_fallback(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        yahoo = FakeProvider([])
        titles = ("reports quarterly results", "launches a new service", "appoints a new chief executive",
                  "receives regulatory approval", "signs a supply agreement")
        rows = [tavily_result(f"Reliance Industries {title}", url=f"https://www.reuters.com/world/india/story-{i}")
                for i, title in enumerate(titles)]
        service = NewsService(self.root, yahoo, tavily_provider=tavily)
        with patch("app.news_intelligence.urlopen", return_value=Response(rows)):
            result = service.get("RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(len(result["events"]), 5)
        self.assertEqual(result["provider"], "Tavily")
        self.assertEqual(yahoo.calls, 0)
        self.assertEqual(service.pipeline_stage()["rows"], 5)

    def test_tavily_timeout_and_quota_fall_back_to_yahoo(self) -> None:
        for failure in (TimeoutError("offline"), HTTPError("https://api.tavily.com/search", 429, "quota", {}, None)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                tavily = TavilyNewsProvider(Path(folder), key_loader=lambda: "fixture-key")
                with patch("app.news_intelligence.urlopen", side_effect=failure):
                    result = NewsService(Path(folder), FakeProvider([article("Reliance Industries reports results")]),
                                         tavily_provider=tavily).get("RELIANCE.NS", company_hint="Reliance Industries Limited")
                self.assertEqual(result["provider"], "mock news")
                self.assertEqual(tavily.health()["status"], "DEGRADED")
                self.assertEqual(tavily.health()["requests"], 1)

    def test_tavily_budget_blocks_network_and_preserves_fallback(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key", daily_budget=0)
        with patch("app.news_intelligence.urlopen") as call:
            result = NewsService(self.root, FakeProvider([article("Reliance Industries reports results")]),
                                 tavily_provider=tavily).get("RELIANCE.NS", company_hint="Reliance Industries Limited")
        call.assert_not_called()
        self.assertEqual(result["provider"], "mock news")
        self.assertEqual(tavily.health()["requests"], 0)

    def test_tavily_plan_quota_circuits_then_uses_fallback(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        quota = HTTPError("https://api.tavily.com/search", 432, "plan limit", {}, None)
        with patch("app.news_intelligence.urlopen", side_effect=quota) as call:
            result = NewsService(self.root, FakeProvider([article("Reliance Industries reports results")]),
                                 tavily_provider=tavily).get("RELIANCE.NS", company_hint="Reliance Industries Limited")
            with self.assertRaises(Exception):
                tavily.fetch("RELIANCE.NS", 5, "Reliance Industries Limited")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["provider"], "mock news")
        self.assertEqual(tavily.health()["status"], "FAILED")

    def test_tavily_health_is_separate_from_market_pipeline(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "")
        stage = NewsService(self.root, FakeProvider([]), tavily_provider=tavily).pipeline_stage()
        self.assertEqual(stage["status"], "UNAVAILABLE")
        self.assertEqual(stage["provider"], "Tavily")
        self.assertEqual(stage["requests"], 0)

    def test_tavily_unknown_publication_time_is_not_invented(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        with patch("app.news_intelligence.urlopen", return_value=Response([tavily_result(dated=False)])):
            rows = tavily.fetch("RELIANCE.NS", 5, "Reliance Industries Limited")
        event = normalize_article(rows[0], "RELIANCE.NS", "Reliance Industries Limited",
                                  datetime.now(timezone.utc), "Tavily")
        self.assertIsNone(event["published_at"])
        self.assertEqual(event["publication_status"], "unknown")
        self.assertEqual(event["sentiment"], "uncertain")

    def test_cross_provider_duplicate_prefers_authoritative_link(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        yahoo = FakeProvider([article("Reliance Industries reports quarterly results")])
        with patch("app.news_intelligence.urlopen", return_value=Response([tavily_result()])):
            result = NewsService(self.root, yahoo, tavily_provider=tavily).get(
                "RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["url"], "https://www.reuters.com/world/india/reliance-results")
        self.assertEqual(result["news_pipeline"]["silver_rows"], 1)

    def test_empty_chain_stays_no_evidence(self) -> None:
        tavily = TavilyNewsProvider(self.root, key_loader=lambda: "fixture-key")
        with patch("app.news_intelligence.urlopen", return_value=Response([])):
            result = NewsService(self.root, FakeProvider([]), tavily_provider=tavily).get(
                "RELIANCE.NS", company_hint="Reliance Industries Limited")
        self.assertEqual(result["message"], "No verified recent evidence.")


if __name__ == "__main__":
    unittest.main()
