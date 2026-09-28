"""Source-linked, deterministic news context for Indian equity forecasts."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import yfinance as yf
from app.usage_budget import DailyUsageBudget


RECENT_DAYS = 14
CACHE_SECONDS = 15 * 60
REFRESH_SECONDS = 60
STALE_SECONDS = 24 * 60 * 60
MAX_EVENTS = 8
TAVILY_CACHE_SECONDS = 10 * 60
TAVILY_DAILY_BUDGET = 12
TAVILY_NAME = "Tavily"
SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.^-]{0,18}\.(?:NS|BO)\Z")
FOREIGN_LISTING = re.compile(r"\b(?:NYSE|NASDAQ|AMEX|LSE|TSX|OTC)\s*:\s*[A-Z0-9.-]+\b", re.I)
SOCIAL_SOURCES = {"linkedin", "facebook", "instagram", "reddit", "youtube", "x", "twitter"}
CORPORATE_SUFFIX = re.compile(r"\b(?:limited|ltd|incorporated|inc|corporation|corp)\b", re.I)
EVENT_PATTERNS = (
    ("guidance", r"\b(?:guidance|outlook|forecast revision)\b"),
    ("earnings", r"\b(?:earnings|quarterly|results|profit|revenue|sales|guidance)\b"),
    ("management", r"\b(?:ceo|cfo|chairman|chairperson|board|resigns?|appoints?)\b"),
    ("regulatory", r"\b(?:regulator|regulatory|sebi|approval|probe|investigation|fine|penalty)\b"),
    ("legal", r"\b(?:lawsuit|litigation|court|tribunal|settlement)\b"),
    ("deal/order", r"\b(?:deal|orders?|contract|agreement|wins? tender)\b"),
    ("product", r"\b(?:launches?|product|service|contract|order|partnership|payments?|cbdc|digital rupee)\b"),
    ("merger/acquisition", r"\b(?:merger|acquisition|acquires?|takeover|demerger)\b"),
    ("sector", r"\b(?:sector|industry|commodity|refiner|telecom|banking)\b"),
    ("macro", r"\b(?:inflation|interest rates?|rbi|budget|tariff|economy|gdp)\b"),
    ("analyst/research", r"\b(?:analyst|brokerage|research|rating|target price)\b"),
)
POSITIVE_CUES = re.compile(r"\b(?:beats? estimates|profit rises?|revenue grows?|raises? guidance|wins? (?:a )?contract|receives? approval)\b", re.I)
NEGATIVE_CUES = re.compile(r"\b(?:misses? estimates|profit falls?|revenue declines?|cuts? guidance|faces? (?:a )?probe|regulatory fine)\b", re.I)
TRUSTED_HOSTS = {"reuters.com", "nseindia.com", "bseindia.com", "business-standard.com",
                 "economictimes.indiatimes.com", "livemint.com", "moneycontrol.com",
                 "cnbctv18.com", "financialexpress.com", "thehindu.com"}
TRUSTED_PUBLISHERS = {"reuters", "business standard", "economic times", "mint", "moneycontrol",
                      "cnbc tv18", "financial express", "the hindu", "nse", "bse"}


class NewsProvider(Protocol):
    name: str

    def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict[str, Any]]: ...


class YahooNewsProvider:
    name = "Yahoo Finance via yfinance"

    def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict[str, Any]]:
        return yf.Ticker(symbol).get_news(count=count)


class GoogleNewsRssProvider:
    name = "Google News RSS"

    def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict[str, Any]]:
        name = _plain(CORPORATE_SUFFIX.sub("", company_name), 90) or symbol.rsplit(".", 1)[0]
        query = urlencode({"q": f'"{name}" India when:{RECENT_DAYS}d',
                           "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        request = Request(f"https://news.google.com/rss/search?{query}",
                          headers={"User-Agent": "Mozilla/5.0 (compatible; KronosCopilot/1.0)"})
        with urlopen(request, timeout=8) as response:
            root = ElementTree.fromstring(response.read(1_000_000))
        articles = []
        for item in root.findall("./channel/item")[:count]:
            publisher = _plain(item.findtext("source"), 80)
            title = _plain(item.findtext("title"), 220)
            if publisher and title.endswith(f" - {publisher}"):
                title = title[:-(len(publisher) + 3)]
            try:
                published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, IndexError):
                continue
            articles.append({"id": item.findtext("guid") or "", "content": {
                "title": title, "canonicalUrl": {"url": item.findtext("link")},
                "pubDate": published, "provider": {"displayName": publisher or "Google News RSS"}}})
        return articles


def _tavily_key() -> str:
    if os.environ.get("TAVILY_NEWS_DISABLED") == "1":
        return ""
    if os.environ.get("TAVILY_API_KEY"):
        return os.environ["TAVILY_API_KEY"].strip()
    local = Path(__file__).resolve().parents[1] / ".env.local"
    try:
        for line in local.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "TAVILY_API_KEY":
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _extended_window() -> int | None:
    try:
        value = int(os.environ.get("TAVILY_NEWS_FALLBACK_DAYS", "0"))
    except ValueError:
        return None
    return max(4, min(value, 7)) if value else None


class TavilyRequestError(Exception):
    def __init__(self, status: int | None = None):
        self.status = status
        super().__init__(f"Tavily HTTP {status}" if status else "Tavily request unavailable")


class TavilyNewsProvider:
    name = TAVILY_NAME

    def __init__(self, cache_dir: Path, *, key_loader=None, window_days: int = 3,
                 fallback_days: int | None = None, daily_budget: int = TAVILY_DAILY_BUDGET):
        self.cache_dir = cache_dir
        self.key_loader = key_loader or _tavily_key
        self.window_days = max(1, min(int(window_days), 3))
        self.fallback_days = max(4, min(int(fallback_days), 7)) if fallback_days else None
        self.daily_budget = daily_budget
        self.usage_budget = DailyUsageBudget(cache_dir / "tavily_usage.sqlite3")
        self._lock = threading.RLock()
        self._budget_date = datetime.now(timezone.utc).date()
        self.requests, self.credits = self.usage_budget.totals("tavily")
        self.last_success: str | None = None
        self.last_failure: str | None = None
        self.latency_ms: int | None = None
        self.consecutive_failures = 0
        self.state = "UNAVAILABLE" if not self.key_loader() else "STALE"
        self.failure_reason = ""
        self.cooldown_until: datetime | None = None

    def enabled(self) -> bool:
        return bool(self.key_loader())

    def cache_identity(self, symbol: str, company_name: str) -> str:
        return json.dumps({"provider": "tavily", "symbol": symbol,
                           "query": self._query(symbol, company_name), "days": self.window_days,
                           "fallback_days": self.fallback_days}, sort_keys=True)

    @staticmethod
    def _query(symbol: str, company_name: str) -> str:
        name = _plain(CORPORATE_SUFFIX.sub("", company_name), 90) or symbol.rsplit(".", 1)[0]
        exchange = "NSE" if symbol.endswith(".NS") else "BSE"
        return f'"{name}" {symbol.rsplit(".", 1)[0]} {exchange} India company stock'

    def _query_cache(self, identity: str) -> Path:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"tavily-query-{digest}.json"

    def _search(self, symbol: str, query: str, days: int, count: int, key: str) -> list[dict[str, Any]]:
        identity = json.dumps({"provider": "tavily", "symbol": symbol, "query": query,
                               "days": days, "max_results": count}, sort_keys=True)
        target = self._query_cache(identity)
        try:
            cached = json.loads(target.read_text(encoding="utf-8"))
            cached_at = _utc(cached.get("retrieved_at"))
            if cached_at and (datetime.now(timezone.utc) - cached_at).total_seconds() < TAVILY_CACHE_SECONDS:
                return cached["results"] if isinstance(cached["results"], list) else []
        except (OSError, ValueError, TypeError, KeyError):
            pass
        now = datetime.now(timezone.utc)
        if self.cooldown_until and now < self.cooldown_until:
            raise TavilyRequestError()
        if not self.usage_budget.reserve("tavily", self.daily_budget, now.date().isoformat()):
            self.state, self.failure_reason = "DEGRADED", "Local Tavily request budget reached"
            raise TavilyRequestError()
        self.requests, self.credits = self.usage_budget.totals("tavily")
        body = {"query": query, "topic": "news", "search_depth": "basic", "max_results": min(count, 5),
                "start_date": (now - timedelta(days=days)).date().isoformat(),
                "include_published_date": True, "filter_by_published_date": False,
                "include_answer": False, "include_raw_content": False, "include_images": False,
                "auto_parameters": False, "include_usage": True}
        request = Request("https://api.tavily.com/search", data=json.dumps(body).encode("utf-8"),
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          method="POST")
        started = time.monotonic()
        try:
            with urlopen(request, timeout=8) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise TavilyRequestError()
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise TavilyRequestError()
            usage = payload.get("usage") or {}
            if isinstance(usage, dict) and isinstance(usage.get("credits"), (int, float)):
                self.usage_budget.add_credits("tavily", int(usage["credits"]))
                self.requests, self.credits = self.usage_budget.totals("tavily")
            self.latency_ms = round((time.monotonic() - started) * 1000)
            self.last_success = datetime.now(timezone.utc).isoformat()
            self.consecutive_failures = 0
            self.state, self.failure_reason = "HEALTHY", ""
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            bronze = {"provider": "tavily", "symbol": symbol, "query": query,
                      "window_days": days, "retrieved_at": self.last_success, "response": payload}
            serialized = json.dumps(bronze, sort_keys=True).encode("utf-8")
            digest = hashlib.sha256(serialized).hexdigest()
            bronze_path = self.cache_dir / "bronze" / f"{digest}.json"
            bronze_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with bronze_path.open("xb") as handle:
                    handle.write(serialized)
            except FileExistsError:
                pass
            results = [{"item": item, "bronze_sha256": digest, "window_days": days} for item in payload["results"]
                       if isinstance(item, dict)]
            temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps({"retrieved_at": self.last_success, "results": results}), encoding="utf-8")
            os.replace(temporary, target)
            return results
        except HTTPError as error:
            self._failed(f"HTTP {error.code}", error.code)
            raise TavilyRequestError(error.code) from None
        except (URLError, OSError, ValueError, TypeError, TavilyRequestError):
            self._failed("Provider request failed", None)
            raise TavilyRequestError() from None

    def _failed(self, reason: str, status: int | None) -> None:
        self.last_failure = datetime.now(timezone.utc).isoformat()
        self.consecutive_failures += 1
        self.failure_reason = reason
        self.state = "FAILED" if status in {401, 403, 432, 433} else "DEGRADED"
        if status in {401, 403, 432, 433}:
            self.cooldown_until = datetime.now(timezone.utc) + timedelta(days=1)
        elif status == 429:
            self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=10)

    def fetch(self, symbol: str, count: int, company_name: str = "") -> list[dict[str, Any]]:
        with self._lock:
            key = self.key_loader()
            if not key:
                self.state = "UNAVAILABLE"
                raise TavilyRequestError()
            query = self._query(symbol, company_name)
            matches = self._search(symbol, query, self.window_days, count, key)
            if not matches and self.fallback_days:
                matches = self._search(symbol, query, self.fallback_days, count, key)
            articles = []
            for match in matches:
                item = match["item"]
                url = item.get("url")
                host = urlparse(url).hostname if isinstance(url, str) else None
                articles.append({"id": item.get("id"), "content": {
                    "id": item.get("id"), "title": item.get("title"),
                    "canonicalUrl": {"url": url}, "pubDate": item.get("published_date"),
                    "summary": item.get("content"), "provider": {"displayName": host or "Web source"}},
                    "tavily_query": query, "tavily_window_days": match["window_days"],
                    "tavily_score": item.get("score"), "bronze_sha256": match["bronze_sha256"]})
            return articles

    def health(self) -> dict[str, Any]:
        with self._lock:
            self.requests, self.credits = self.usage_budget.totals("tavily")
            status = self.state if self.enabled() else "UNAVAILABLE"
            if status == "HEALTHY" and self.last_success:
                if (datetime.now(timezone.utc) - _utc(self.last_success)).total_seconds() > TAVILY_CACHE_SECONDS:
                    status = "STALE"
            return {"status": status, "requests": self.requests, "credits": self.credits,
                    "last_success": self.last_success, "last_failure": self.last_failure,
                    "latency_ms": self.latency_ms, "consecutive_failures": self.consecutive_failures,
                    "reason": self.failure_reason or ("TAVILY_API_KEY is not configured" if status == "UNAVAILABLE" else "")}


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        try:
            parsed = parsedate_to_datetime(str(value))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (ValueError, TypeError, IndexError):
            return None


def _plain(value: Any, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))).strip()
    return cleaned[:limit].rstrip()


def _words(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _linked_url(value: Any) -> str | None:
    address = value.get("url") if isinstance(value, dict) else value
    if not isinstance(address, str):
        return None
    parsed = urlparse(address)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        return None
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return None
    except ValueError:
        pass
    return address


def _source_quality(url: str, publisher: str) -> str:
    host = (urlparse(url).hostname or "").removeprefix("www.").lower()
    name = _words(publisher)
    trusted_host = any(host == trusted or host.endswith(f".{trusted}") for trusted in TRUSTED_HOSTS)
    trusted_name = any(name == trusted or name.startswith(f"{trusted} ") for trusted in TRUSTED_PUBLISHERS)
    return "high" if trusted_host or trusted_name else "unrated"


def _same_story(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = urlparse(left["url"]), urlparse(right["url"])
    same_host = (a.hostname or "").removeprefix("www.") == (b.hostname or "").removeprefix("www.")
    if same_host and a.path.strip("/") and a.path.rstrip("/") == b.path.rstrip("/"):
        return True
    similarity = SequenceMatcher(None, _words(left["title"]), _words(right["title"])).ratio()
    if similarity < (0.76 if same_host else 0.87):
        return False
    first, second = _utc(left.get("published_at")), _utc(right.get("published_at"))
    return abs((first - second).total_seconds()) <= 36 * 3600 if first and second else similarity >= 0.94


def _prefer_article(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def quality(item: dict[str, Any]) -> tuple[int, int, int, int]:
        return (int(item["source_quality"] == "high"), int(bool(item["published_at"])),
                int(urlparse(item["url"]).hostname != "news.google.com"),
                int(item["provenance"]["provider"] == TAVILY_NAME))
    return max((left, right), key=quality)


def _deduplicate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    distinct: list[dict[str, Any]] = []
    for event in events:
        match = next((index for index, current in enumerate(distinct) if _same_story(event, current)), None)
        if match is None:
            distinct.append(event)
        else:
            distinct[match] = _prefer_article(distinct[match], event)
    return distinct


@lru_cache(maxsize=1)
def _instrument_names() -> dict[str, str]:
    try:
        from app.instrument_search import load_cache

        cached = load_cache()
        return {item.yahoo_symbol: item.company_name for item in cached[0]} if cached else {}
    except (ImportError, OSError, ValueError):
        return {}


def _relevance(raw: dict[str, Any], title: str, summary: str, symbol: str, company_name: str) -> tuple[float, str]:
    if FOREIGN_LISTING.search(title):
        return 0.0, "foreign listing in headline"
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    tagged = raw.get("relatedTickers") or content.get("relatedTickers") or []
    if symbol in {str(item).upper() for item in tagged if isinstance(item, str)}:
        return 0.98, "provider ticker tag"
    base = symbol.rsplit(".", 1)[0]
    title_words = _words(title)
    summary_words = _words(summary)
    name = _words(CORPORATE_SUFFIX.sub("", company_name))
    if name and len(name) >= 7 and name in title_words:
        return 0.92, "official company name in headline"
    if re.search(rf"\b{re.escape(base)}\b", title, re.I):
        return 0.84, "exact ticker in headline"
    if name and len(name) >= 7 and name in summary_words and base.lower() in title_words.split():
        return 0.78, "ticker headline and company name in excerpt"
    if name and len(name) >= 7 and name in summary_words:
        return 0.72, "official company name in provider excerpt"
    return 0.0, "no specific company match"


def normalize_article(raw: dict[str, Any], symbol: str, company_name: str,
                      retrieved_at: datetime, provider: str) -> dict[str, Any] | None:
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    title = _plain(content.get("title"), 220)
    url = _linked_url(content.get("canonicalUrl") or content.get("clickThroughUrl") or content.get("link"))
    published = _utc(content.get("pubDate") or content.get("providerPublishTime"))
    if not title or not url or (not published and provider != TAVILY_NAME):
        return None
    window_days = raw.get("tavily_window_days", RECENT_DAYS) if provider == TAVILY_NAME else RECENT_DAYS
    if published and (published < retrieved_at - timedelta(days=window_days) or published > retrieved_at + timedelta(minutes=5)):
        return None
    summary = _plain(content.get("summary") or content.get("description"), 220)
    relevance, basis = _relevance(raw, title, summary, symbol, company_name)
    if relevance < 0.7:
        return None
    publisher = content.get("provider")
    source = _plain(publisher.get("displayName") if isinstance(publisher, dict) else publisher or content.get("publisher"), 80)
    if not source:
        source = "Yahoo Finance listing"
    if source.lower() in SOCIAL_SOURCES:
        return None
    category_text = f"{title} {summary}".lower()
    event_type = next((name for name, pattern in EVENT_PATTERNS if re.search(pattern, category_text)), "other")
    if provider == "Google News RSS" and event_type == "other":
        return None
    positive = bool(POSITIVE_CUES.search(title))
    negative = bool(NEGATIVE_CUES.search(title))
    sentiment = ("uncertain" if not published else "mixed" if positive and negative else
                 "positive_cue" if positive else "negative_cue" if negative else "neutral")
    article_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return {"id": article_id, "symbol": symbol, "title": title, "source": source, "url": url,
            "published_at": published.isoformat() if published else None, "publication_status": "known" if published else "unknown",
            "retrieved_at": retrieved_at.isoformat(), "source_quality": _source_quality(url, source),
            "event_type": event_type, "summary": summary, "relevance": relevance,
            "sentiment": sentiment, "context": "Headline cue only; market impact is not inferred.",
            "provenance": {"provider": provider, "provider_article_id": str(content.get("id") or raw.get("id") or ""),
                           "relevance_basis": basis, "query": raw.get("tavily_query") if provider == TAVILY_NAME else None,
                           "window_days": raw.get("tavily_window_days") if provider == TAVILY_NAME else None,
                           "bronze_sha256": raw.get("bronze_sha256") if provider == TAVILY_NAME else None}}


class NewsService:
    def __init__(self, cache_dir: Path, provider: NewsProvider | None = None,
                 fallback_provider: GoogleNewsRssProvider | None = None,
                 tavily_provider: TavilyNewsProvider | None = None):
        self.cache_dir = cache_dir
        self.provider = provider or YahooNewsProvider()
        self.fallback_provider = fallback_provider if fallback_provider is not None else (GoogleNewsRssProvider() if provider is None else None)
        self.tavily_provider = tavily_provider if tavily_provider is not None else (
            TavilyNewsProvider(cache_dir, fallback_days=_extended_window()) if provider is None else None)
        self._lock = threading.RLock()
        self._last_count = 0
        self._last_events = 0
        self._last_impact_status = "NOT_EVALUATED"
        self._last_update: str | None = None

    @staticmethod
    def official_name(symbol: str) -> str:
        return _instrument_names().get(symbol, "")

    def record_impact(self, impact: dict[str, Any]) -> None:
        with self._lock:
            self._last_events = int(impact["events_processed"])
            self._last_impact_status = str(impact["status"])

    def _cache_path(self, symbol: str, company_name: str) -> Path:
        tavily = self.tavily_provider
        identity = json.dumps({"schema": "news_v2", "symbol": symbol, "company_name": company_name,
                               "tavily": tavily.cache_identity(symbol, company_name) if tavily and tavily.enabled() else None},
                              sort_keys=True)
        return self.cache_dir / f"{symbol}.{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}.json"

    def _read(self, target: Path, symbol: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            return payload if (isinstance(payload, dict) and payload.get("symbol") == symbol
                               and isinstance(payload.get("events"), list)
                               and all(isinstance(item, dict) and {"id", "sentiment", "title", "url", "published_at"} <= item.keys()
                                       for item in payload["events"])
                               and payload.get("status") in {"FRESH", "NO_EVIDENCE", "UNAVAILABLE"}
                               and _utc(payload.get("retrieved_at"))) else None
        except (OSError, ValueError, TypeError):
            return None

    def _write(self, target: Path, payload: dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def _response(self, payload: dict[str, Any], status: str, cache_status: str) -> dict[str, Any]:
        events = payload.get("events", [])
        self._last_count = sum(item.get("provenance", {}).get("provider") == TAVILY_NAME for item in events)
        self._last_update = payload.get("retrieved_at")
        providers_used = list(dict.fromkeys(item.get("provenance", {}).get("provider") for item in events))
        return {"symbol": payload["symbol"], "status": status,
                "message": "No verified recent evidence." if not events else "Source-reported headlines; impact is not independently verified.",
                "events": events,
                "positive_evidence": [item["id"] for item in events if item["sentiment"] == "positive_cue"],
                "negative_evidence": [item["id"] for item in events if item["sentiment"] == "negative_cue"],
                "uncertainty": "Headline cues and provider excerpts are not independently verified; coverage may be incomplete.",
                "retrieved_at": payload.get("retrieved_at"), "provider": payload.get("provider"),
                "providers_used": providers_used, "tavily_health": self.tavily_health(),
                "news_pipeline": {"bronze_hashes": list(dict.fromkeys(item.get("provenance", {}).get("bronze_sha256")
                                  for item in events if item.get("provenance", {}).get("bronze_sha256"))),
                                  "silver_rows": len(events),
                                  "gold_positive_cues": sum(item["sentiment"] == "positive_cue" for item in events),
                                  "gold_negative_cues": sum(item["sentiment"] == "negative_cue" for item in events)},
                "cache_status": cache_status}

    def tavily_health(self) -> dict[str, Any]:
        return self.tavily_provider.health() if self.tavily_provider else {
            "status": "UNAVAILABLE", "requests": 0, "credits": 0, "last_success": None,
            "last_failure": None, "latency_ms": None, "consecutive_failures": 0,
            "reason": "Tavily is not configured"}

    def pipeline_stage(self) -> dict[str, Any]:
        health = self.tavily_health()
        return {"status": health["status"], "rows": self._last_count, "last_update": health["last_success"],
                "latency_ms": health["latency_ms"], "provider": TAVILY_NAME, "cache_status": "not_applicable",
                "warnings": [health["reason"]] if health["reason"] else [], "errors": [],
                "events_processed": self._last_events, "impact_status": self._last_impact_status,
                "requests": health["requests"], "credits": health["credits"],
                "last_failure": health["last_failure"], "consecutive_failures": health["consecutive_failures"]}

    def get(self, symbol: str, *, refresh: bool = False, company_hint: str = "") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("Choose an NSE or BSE equity symbol ending in .NS or .BO.")
        now = datetime.now(timezone.utc)
        with self._lock:
            company_name = _instrument_names().get(symbol) or _plain(company_hint, 120)
            target = self._cache_path(symbol, company_name)
            cached = self._read(target, symbol)
            cached_at = _utc(cached.get("retrieved_at")) if cached else None
            age = (now - cached_at).total_seconds() if cached_at else float("inf")
            ttl = TAVILY_CACHE_SECONDS if self.tavily_provider and self.tavily_provider.enabled() else CACHE_SECONDS
            if cached and age < (REFRESH_SECONDS if refresh else ttl):
                return self._response(cached, cached["status"], "hit")
            try:
                events: list[dict[str, Any]] = []
                providers: list[NewsProvider] = []
                if self.tavily_provider and self.tavily_provider.enabled():
                    providers.append(self.tavily_provider)
                providers.append(self.provider)
                if self.fallback_provider and company_name:
                    providers.append(self.fallback_provider)
                provider_errors = []
                for source in providers:
                    if len(events) >= 5:
                        break
                    try:
                        count = 5 if source is self.tavily_provider else 30 if source is self.fallback_provider else 20
                        raw_articles = source.fetch(symbol, count, company_name)
                        if not isinstance(raw_articles, list):
                            raise ValueError("News provider returned an invalid response")
                        candidates = []
                        for raw in raw_articles:
                            if not isinstance(raw, dict):
                                continue
                            article = normalize_article(raw, symbol, company_name, now, source.name)
                            if article:
                                candidates.append(article)
                        events = _deduplicate(events + candidates)
                    except Exception:
                        provider_errors.append(source.name)
                if provider_errors and not events and len(provider_errors) == len(providers):
                    raise RuntimeError("All news providers are unavailable")
                events.sort(key=lambda item: (_utc(item["published_at"]) or datetime.min.replace(tzinfo=timezone.utc),
                                              item["relevance"]), reverse=True)
                active_provider = events[0]["provenance"]["provider"] if events else ", ".join(source.name for source in providers)
                payload = {"symbol": symbol, "status": "FRESH" if events else "NO_EVIDENCE",
                           "events": events[:MAX_EVENTS], "retrieved_at": now.isoformat(),
                           "provider": active_provider}
                self._write(target, payload)
                return self._response(payload, payload["status"], "miss")
            except Exception:
                if cached and age <= STALE_SECONDS:
                    return self._response(cached, "STALE", "stale_hit")
                payload = {"symbol": symbol, "status": "UNAVAILABLE", "events": [],
                           "retrieved_at": now.isoformat(), "provider": self.provider.name}
                try:
                    self._write(target, payload)
                except OSError:
                    pass
                return self._response(payload, "UNAVAILABLE", "miss")
