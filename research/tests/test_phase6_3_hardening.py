"""Offline Phase 6.3 security and evidence contract checks."""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from app import server
from app.evidence_snapshot import create_content, read_snapshot, save_snapshot, snapshot_id
from app.security import AccessGuard, valid_host
from app.usage_budget import DailyUsageBudget
from research.technical_intelligence import analyze


class SecurityHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.DashboardHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, data

    def test_static_allowlist_blocks_private_files_and_traversal(self) -> None:
        self.assertEqual(self.request("HEAD", "/app/dashboard.html")[0], 200)
        self.assertEqual(self.request("HEAD", "/app/dashboard.css")[0], 200)
        status, _, public_body = self.request("GET", "/app/dashboard.html")
        self.assertEqual(status, 200)
        self.assertTrue(public_body.lower().startswith(b"<!doctype html>"))
        for path in ("/.env.local", "/.env", "/.git/config", "/research/market_data.py",
                     "/outputs/forecast_summary.json", "/../.env.local", "/app/../.env.local",
                     "/app/%2e%2e/.env.local", "/%2eenv.local", "/app/server.py",
                     "/app/vendor/../server.py"):
            with self.subTest(path=path):
                status, _, body = self.request("HEAD", path)
                self.assertIn(status, (403, 404))
                self.assertEqual(body, b"")

    def test_lan_authentication_and_expiry_without_running_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            guard = AccessGuard(Path(directory) / "missing.env", clock=lambda: now[0])
            with patch.object(server, "ACCESS_GUARD", guard), patch.object(server.DashboardHandler, "_address", return_value="192.168.1.44"), patch.dict("os.environ", {"KRONOS_LAN_ACCESS_CODE": "local-test-code-123456"}):
                headers = {"Content-Type": "application/json"}
                for route in sorted(server.EXPENSIVE_POST):
                    with self.subTest(route=route):
                        status, _, body = self.request("POST", route, b"{}", headers)
                        self.assertEqual(status, 401)
                        self.assertNotIn(b"local-test-code-123456", body)
                status, _, _ = self.request("GET", "/api/news?symbol=TEST.NS", headers={"X-Kronos-Request": "dashboard"})
                self.assertEqual(status, 401)
                self.assertEqual(self.request("GET", "/api/search?q=tes", headers={"X-Kronos-Request": "dashboard"})[0], 401)
                status, _, _ = self.request("POST", "/api/session", b'{"access_code":"wrong-value-000"}', headers)
                self.assertEqual(status, 401)
                status, returned, body = self.request("POST", "/api/session", b'{"access_code":"local-test-code-123456"}', headers)
                self.assertEqual(status, 200)
                self.assertIn("HttpOnly", returned["Set-Cookie"])
                self.assertIn("SameSite=Strict", returned["Set-Cookie"])
                self.assertNotIn(b"local-test-code-123456", body)
                cookie = returned["Set-Cookie"].split(";", 1)[0]
                with patch.object(server, "generate_explanation", return_value={"cached": True, "explanation": "offline"}) as explanation:
                    status, _, _ = self.request("POST", "/api/explanation", b"{}", {**headers, "Cookie": cookie})
                    self.assertEqual(status, 200)
                    explanation.assert_called_once()
                status, _, _ = self.request("POST", "/api/explanation", b"{}", {**headers, "Cookie": "kronos_session=invalid"})
                self.assertEqual(status, 401)
                now[0] += 8 * 3600 + 1
                status, _, _ = self.request("POST", "/api/explanation", b"{}", {**headers, "Cookie": cookie})
                self.assertEqual(status, 401)

    def test_remote_research_and_cross_origin_denied(self) -> None:
        with patch.object(server.DashboardHandler, "_address", return_value="192.168.1.44"):
            self.assertEqual(self.request("GET", "/api/research/status")[0], 403)
            self.assertEqual(self.request("POST", "/api/session", b"{}", {
                "Content-Type": "application/json", "Origin": "https://evil.example"})[0], 403)

    def test_rate_guard_counts_requests_and_recent_failures(self) -> None:
        now = [1000.0]
        guard = AccessGuard(Path("nonexistent.env"), clock=lambda: now[0])
        self.assertTrue(guard.allow("192.168.1.2", "/api/forecast", 2, 600, daily=2))
        self.assertTrue(guard.allow("192.168.1.2", "/api/forecast", 2, 600, daily=2))
        self.assertFalse(guard.allow("192.168.1.2", "/api/forecast", 2, 600, daily=2))
        guard.record_failure("192.168.1.2", "/api/forecast")
        self.assertEqual(guard.stats("192.168.1.2", "/api/forecast")["daily_count"], 2)
        self.assertEqual(guard.stats("192.168.1.2", "/api/forecast")["recent_failures"], 2)
        now[0] += 601
        self.assertEqual(guard.stats("192.168.1.2", "/api/forecast")["recent_failures"], 0)

    def test_news_cross_site_rejected_before_cost_bearing_work(self) -> None:
        guard = AccessGuard(Path("nonexistent.env"))
        host = f"127.0.0.1:{self.httpd.server_port}"
        blocked = (
            {"Origin": "https://outside.example", "Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "null"},
            {"Origin": "http://[invalid"},
            {"Origin": f"http://{host}/bad"},
            {"Origin": f"https://{host}"},
            {"Origin": f"http://{host}", "Sec-Fetch-Site": "cross-site"},
            {"Referer": "https://outside.example/page"},
        )
        with patch.object(server, "ACCESS_GUARD", guard), patch.object(
                server, "build_news_research_payload", return_value={"symbol": "TEST.NS"}) as work:
            for headers in blocked:
                with self.subTest(headers=headers):
                    status, _, _ = self.request("GET", "/api/news?symbol=TEST.NS&refresh=1",
                                                headers={**headers, "X-Kronos-Request": "dashboard"})
                    self.assertEqual(status, 403)
            self.assertEqual(work.call_count, 0)
            self.assertEqual(guard.stats("127.0.0.1", "/api/news")["daily_count"], 0)
            self.assertEqual(self.request("GET", "/api/news?symbol=TEST.NS")[0], 403)
            for headers in ({}, {"Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"}):
                self.assertEqual(self.request("GET", "/api/news?symbol=TEST.NS",
                                              headers={**headers, "X-Kronos-Request": "dashboard"})[0], 200)
            self.assertEqual(work.call_count, 2)

    def test_protected_routes_reject_bad_host_origin_and_method(self) -> None:
        host = f"127.0.0.1:{self.httpd.server_port}"
        with patch.object(server, "build_news_research_payload") as work:
            self.assertEqual(self.request("GET", "/api/news", headers={"Host": "evil.example"})[0], 404)
            self.assertEqual(self.request("GET", "/api/news", headers={"Host": "127.0.0.1:bad"})[0], 404)
            for route in ("/api/news", "/api/search", "/api/symbol-search", "/api/evidence-snapshot"):
                self.assertEqual(self.request("GET", route, headers={"Origin": "http://elsewhere.example"})[0], 403)
            for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
                status, headers, _ = self.request(method, "/api/news?symbol=TEST.NS")
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("Allow"), "GET, HEAD, POST")
            self.assertEqual(self.request("HEAD", "/api/news?symbol=TEST.NS")[0], 404)
            self.assertEqual(self.request("POST", "/api/news", b"{}", {
                "Origin": f"http://{host}", "Content-Type": "application/json"})[0], 404)
            work.assert_not_called()
        self.assertFalse(valid_host("127.0.0.1:bad"))

    def test_authenticated_lan_news_and_session_bypass_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            guard = AccessGuard(Path(directory) / "missing.env", clock=lambda: now[0])
            host = f"192.168.1.88:{self.httpd.server_port}"
            with patch.object(server, "ACCESS_GUARD", guard), patch.object(
                    server.DashboardHandler, "_address", return_value="192.168.1.44"), patch.dict(
                    "os.environ", {"KRONOS_LAN_ACCESS_CODE": "synthetic-test-code-12345"}), patch.object(
                    server, "build_news_research_payload", return_value={"symbol": "TEST.NS"}) as work:
                route = "/api/news?symbol=TEST.NS&refresh=1"
                self.assertEqual(self.request("GET", route, headers={"Host": host, "X-Kronos-Request": "dashboard"})[0], 401)
                self.assertEqual(self.request("GET", route, headers={"Host": host,
                    "Cookie": "kronos_session=forged", "X-Kronos-Request": "dashboard"})[0], 401)
                token = guard.login("192.168.1.44", "synthetic-test-code-12345")
                headers = {"Host": host, "Cookie": f"kronos_session={token}",
                           "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin",
                           "X-Kronos-Request": "dashboard"}
                self.assertEqual(self.request("GET", route, headers=headers)[0], 200)
                self.assertEqual(work.call_count, 1)
                self.assertEqual(self.request("GET", route, headers={**headers,
                    "Origin": "https://outside.example", "Sec-Fetch-Site": "cross-site"})[0], 403)
                self.assertEqual(work.call_count, 1)
                now[0] += 8 * 3600 + 1
                self.assertEqual(self.request("GET", route, headers=headers)[0], 401)
                self.assertEqual(work.call_count, 1)
                self.assertEqual(guard.stats("192.168.1.44", "/api/news")["daily_count"], 1)

    def test_security_headers_on_public_and_json_responses(self) -> None:
        for route in ("/app/dashboard.html", "/api/pipeline"):
            _, headers, _ = self.request("HEAD" if route.startswith("/app/") else "GET", route)
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(headers["X-Frame-Options"], "DENY")


class EvidenceTests(unittest.TestCase):
    def test_news_why_view_exposes_matching_immutable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path, input_path, forecast_path = (root / name for name in ("summary.json", "input.csv", "forecast.csv"))
            summary = {"input_source": "TEST.NS live 5-minute data", "model": "Kronos-base",
                       "direction": "up", "forecast_rows": 1, "last_observed_close": 100,
                       "forecast_final_close": 101, "forecast_pct_change": 1}
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            input_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-25T15:15:00+05:30,100,101,99,100,10,1000\n", encoding="utf-8")
            forecast_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-28T09:15:00+05:30,101,102,100,101,10,1010\n", encoding="utf-8")
            manifest_path = root / "latest.json"
            manifest_path.write_text(json.dumps({"symbol": "TEST.NS", "capture_id": "capture",
                                                 "provider": "yahoo", "quality": {"state": "PASS"}}), encoding="utf-8")
            pipeline = SimpleNamespace(_latest=manifest_path,
                                       matching_technicals=lambda symbol, fingerprint: {
                                           "as_of": "2026-09-25T15:15:00+05:30", "trend": "bullish",
                                           "regime": "SIDEWAYS", "indicators": [], "analysis_version": "test-version"})
            news = {"symbol": "TEST.NS", "status": "NO_EVIDENCE", "events": [],
                    "provider": "offline", "providers_used": [], "cache_status": "hit",
                    "news_pipeline": {"bronze_hashes": []}}
            with patch.object(server, "SUMMARY_PATH", summary_path), patch.object(server, "UPLOADED_DATA_PATH", input_path), \
                 patch.object(server, "FORECAST_PATH", forecast_path), patch.object(server, "EVIDENCE_DIR", root / "snapshots"), \
                 patch.object(server, "PRODUCT_PIPELINE", pipeline), patch.object(server.NEWS_SERVICE, "get", return_value=news), \
                 patch.object(server.NEWS_SERVICE, "official_name", return_value="Test Limited"), \
                 patch.object(server.NEWS_SERVICE, "record_impact"), patch.object(server.NEWS_SERVICE, "cache_dir", root / "news"):
                payload = server.build_news_research_payload("TEST.NS")
            self.assertIn("evidence_snapshot_id", payload)
            self.assertEqual(payload["forecast_fingerprint"], read_snapshot(root / "snapshots", payload["evidence_snapshot_id"])["evidence"]["kronos"]["forecast_fingerprint"])
            self.assertEqual(payload["research_outlook"]["why"], read_snapshot(root / "snapshots", payload["evidence_snapshot_id"])["evidence"]["research_view"]["why"])

    def test_snapshot_is_deterministic_immutable_and_complete(self) -> None:
        summary = {"model": "Kronos-base", "direction": "up", "forecast_rows": 24,
                   "last_observed_close": 100.0, "forecast_final_close": 102.0}
        market = {"symbol": "TEST.NS", "capture_id": "capture", "provider": "yahoo",
                  "bronze": {"sha256": "bronze"}, "silver": {"sha256": "silver"},
                  "gold": {"sha256": "technical-gold"}, "quality": {"state": "PASS"},
                  "provenance": {"cache_hit": True}, "retrieved_at": "2026-09-26T00:00:00+00:00"}
        technicals = {"as_of": "2026-09-25T09:30:00+05:30", "regime": "SIDEWAYS",
                      "trend": "bullish", "indicators": [{"indicator": "EMA50", "value": 100.0}]}
        news = {"provider": "Tavily", "providers_used": ["Tavily"], "cache_status": "hit",
                "news_pipeline": {"bronze_hashes": ["news-bronze"]},
                "events": [{"id": "article-1", "url": "https://example.com/one"}]}
        impact = {"events": [{"event_id": "event-1"}], "score": 0.1,
                  "uncertainty_flags": ["UNCONFIRMED_EVENT"], "analysis_version": "news_impact_v1"}
        outlook = {"preliminary_research_view": "NO_STRONG_EDGE", "confidence": "LOW",
                   "why": "Evidence conflicts", "supporting_evidence": ["Kronos up"],
                   "contradicting_evidence": ["Trend mixed"], "primary_risk": "No edge"}
        content = create_content(symbol="TEST.NS", exchange="NSE", summary=summary,
                                 fingerprint="forecast-fp", forecast_sha256="forecast-hash",
                                 input_sha256="input-hash", market=market, technicals=technicals,
                                 news=news, impact=impact, outlook=outlook,
                                 news_gold={"sha256": "news-gold"}, technical_version="phase3@sha256")
        self.assertEqual(snapshot_id(content), snapshot_id(json.loads(json.dumps(content))))
        self.assertEqual(content["market_data"]["silver_sha256"], "silver")
        self.assertEqual(content["kronos"]["forecast_sha256"], "forecast-hash")
        self.assertEqual(content["technicals"]["evidence_reference"], "technical-gold")
        self.assertEqual(content["technicals"]["version"], "phase3@sha256")
        self.assertEqual(content["news"]["gold_sha256"], "news-gold")
        self.assertEqual(content["research_view"]["confidence"]["value"], None)
        self.assertNotIn("API_KEY", json.dumps(content))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = save_snapshot(root, content)
            second = save_snapshot(root, content)
            self.assertEqual(first, second)
            self.assertEqual(read_snapshot(root, first["snapshot_id"]), first)
            self.assertIsNone(read_snapshot(root, "../invalid"))

    def test_market_capture_not_attributed_without_matching_technicals(self) -> None:
        content = create_content(symbol="TEST.NS", exchange="NSE", summary={}, fingerprint="fp",
                                 forecast_sha256="a", input_sha256="b", market={"symbol": "TEST.NS", "capture_id": "old"},
                                 technicals=None, news={}, impact={}, outlook={})
        self.assertIsNone(content["market_data"]["capture_id"])
        self.assertEqual(content["market_data"]["input_sha256"], "b")

    def test_degraded_snapshot_tracks_material_news_without_volatile_fields(self) -> None:
        base = dict(symbol="TEST.NS", exchange="NSE", summary={}, fingerprint="fp",
                    forecast_sha256="forecast", input_sha256="input", market=None,
                    technicals=None, outlook={"why": "Source-linked headline cues"}, news_gold=None)
        article = {"id": "fixed-id", "symbol": "TEST.NS", "title": "Company signs contract",
                   "summary": "Contract details", "source": "Example", "url": "https://example.test/one",
                   "published_at": "2026-09-25T00:00:00+00:00", "retrieved_at": "one",
                   "provenance": {"provider": "offline", "api_key": "SECRET_NEVER_COPY"},
                   "api_key": "SECRET_NEVER_COPY"}
        impact = {"events": [{"event_id": "fixed-event", "headline": article["title"],
                              "url": article["url"], "article_ids": [article["id"]], "impact": 0.1}],
                  "score": 0.1}
        def content(changes=None, impact_value=None):
            event = {**article, **(changes or {})}
            return create_content(**base, news={"provider": "offline", "events": [event]},
                                  impact=impact if impact_value is None else impact_value)
        original = content()
        self.assertEqual(original["news"]["evidence_status"], "DEGRADED")
        self.assertEqual(original["news"]["article_evidence"][0]["title"], article["title"])
        self.assertNotIn("SECRET_NEVER_COPY", json.dumps(original))
        self.assertEqual(snapshot_id(original), snapshot_id(content({"retrieved_at": "two"})))
        self.assertNotEqual(snapshot_id(original), snapshot_id(content({"title": "Company cancels contract"})))
        self.assertNotEqual(snapshot_id(original), snapshot_id(content({"summary": "Different content"})))
        self.assertNotEqual(snapshot_id(original), snapshot_id(content({"url": "https://example.test/two"})))
        self.assertNotEqual(snapshot_id(original), snapshot_id(content(impact_value={**impact,
            "events": [{**impact["events"][0], "headline": "Different impact evidence"}]})))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(save_snapshot(Path(directory), original)["snapshot_id"], snapshot_id(original))

    def test_degraded_server_view_is_grounded_or_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path, input_path, forecast_path = (root / name for name in ("summary.json", "input.csv", "forecast.csv"))
            summary_path.write_text(json.dumps({"input_source": "TEST.NS live 5-minute data",
                                                "model": "Kronos-base", "direction": "up",
                                                "last_observed_close": 100, "forecast_final_close": 101}), encoding="utf-8")
            input_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-25T15:15:00+05:30,100,101,99,100,10,1000\n", encoding="utf-8")
            forecast_path.write_text("timestamps,open,high,low,close,volume,amount\n2026-09-28T09:15:00+05:30,101,102,100,101,10,1010\n", encoding="utf-8")
            manifest_path = root / "latest.json"
            manifest_path.write_text(json.dumps({"symbol": "TEST.NS", "provider": "offline"}), encoding="utf-8")
            pipeline = SimpleNamespace(_latest=manifest_path, matching_technicals=lambda *_: None)
            published = datetime.now(timezone.utc).isoformat()
            def news(title):
                return {"symbol": "TEST.NS", "status": "FRESH", "provider": "offline",
                        "events": [{"id": "fixed-id", "symbol": "TEST.NS", "title": title,
                                    "summary": "Source report", "source": "Example",
                                    "url": "https://example.test/fixed", "published_at": published,
                                    "source_quality": "high", "provenance": {"provider": "offline"}}],
                        "news_pipeline": {"bronze_hashes": []}}
            with patch.object(server, "SUMMARY_PATH", summary_path), patch.object(server, "UPLOADED_DATA_PATH", input_path), \
                 patch.object(server, "FORECAST_PATH", forecast_path), patch.object(server, "EVIDENCE_DIR", root / "snapshots"), \
                 patch.object(server, "PRODUCT_PIPELINE", pipeline), patch.object(server.NEWS_SERVICE, "official_name", return_value="Test Limited"), \
                 patch.object(server.NEWS_SERVICE, "record_impact"), patch.object(server, "save_gold", side_effect=OSError):
                with patch.object(server.NEWS_SERVICE, "get", return_value=news("Test Limited signs contract")):
                    first = server.build_news_research_payload("TEST.NS")
                with patch.object(server.NEWS_SERVICE, "get", return_value=news("Test Limited cancels contract")):
                    second = server.build_news_research_payload("TEST.NS")
                self.assertNotEqual(first["evidence_snapshot_id"], second["evidence_snapshot_id"])
                self.assertIn("degraded", first["research_outlook"]["why"].lower())
                saved = read_snapshot(root / "snapshots", first["evidence_snapshot_id"])["evidence"]
                self.assertEqual(saved["news"]["evidence_status"], "DEGRADED")
                self.assertEqual(saved["news"]["article_evidence"][0]["title"], "Test Limited signs contract")
                self.assertEqual(saved["research_view"]["why"], first["research_outlook"]["why"])
                with patch.object(server.NEWS_SERVICE, "get", return_value=news("Test Limited signs contract")), \
                     patch.object(server, "save_snapshot", side_effect=OSError):
                    unavailable = server.build_news_research_payload("TEST.NS")
                self.assertNotIn("research_outlook", unavailable)
                self.assertNotIn("evidence_snapshot_id", unavailable)

    def test_chart_ema_uses_gold_context_not_64_display_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = root / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            forecast_path = root / "forecast.csv"
            future = pd.date_range("2026-09-28 09:15", periods=24, freq="5min", tz="Asia/Kolkata")
            pd.DataFrame({"timestamps": future, "close": [110.0] * 24}).to_csv(forecast_path, index=False)
            times = pd.date_range("2026-09-23 09:15", periods=400, freq="5min", tz="Asia/Kolkata")
            close = [100 + index / 100 + (index % 7) for index in range(400)]
            frame = pd.DataFrame({"timestamps": times, "open": close, "high": [x + 1 for x in close],
                                  "low": [x - 1 for x in close], "close": close,
                                  "volume": [1000] * 400, "amount": [100000] * 400})
            with patch.object(server, "SUMMARY_PATH", summary_path), patch.object(server, "FORECAST_PATH", forecast_path):
                payload = server.build_dashboard_payload({"input_source": "TEST.NS live 5-minute data", "model": "Kronos-base",
                                                          "forecast_rows": 24, "input_rows": 400}, frame)
            gold = analyze(frame.rename(columns={"timestamps": "timestamp"}))
            expected = next(item["value"] for item in gold["indicators"] if item["indicator"] == "EMA50")
            actual = payload["chart"]["analytical_ema"]["ema50"][-1]["value"]
            self.assertAlmostEqual(actual, expected, places=8)
            self.assertEqual(len(payload["chart"]["analytical_ema"]["ema50"]), 64)


class UsageBudgetTests(unittest.TestCase):
    def test_daily_budget_survives_restart_and_resets_next_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.sqlite3"
            first = DailyUsageBudget(path)
            self.assertTrue(first.reserve("tavily", 2, "2026-09-27"))
            first.add_credits("tavily", 1, "2026-09-27")
            second = DailyUsageBudget(path)
            self.assertEqual(second.totals("tavily", "2026-09-27"), (1, 1))
            self.assertTrue(second.reserve("tavily", 2, "2026-09-27"))
            self.assertFalse(second.reserve("tavily", 2, "2026-09-27"))
            self.assertTrue(second.reserve("tavily", 2, "2026-09-28"))
