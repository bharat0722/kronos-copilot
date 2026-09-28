"""Deterministic, uncalibrated news evidence for a provisional research outlook."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


VERSION = "news_impact_v1"
MAX_OUTLOOK_INFLUENCE = 1  # One category toward NO_STRONG_EDGE; never reverse direction.
CORPORATE_WORDS = re.compile(r"\b(?:limited|ltd|inc|corporation|corp)\b", re.I)
POSITIVE = re.compile(
    r"\b(?:wins? .{0,50}(?:contract|order|tender)|beats? (?:estimates|expectations)|"
    r"profit (?:rises?|grows?|jumps?)|raises? guidance|receives? approval|"
    r"(?:rating )?upgraded?|announces? buyback)\b", re.I)
NEGATIVE = re.compile(
    r"\b(?:loses? .{0,40}(?:contract|order)|misses? (?:estimates|expectations)|"
    r"profit (?:falls?|declines?|drops?)|cuts? guidance|(?:regulatory )?(?:probe|investigation|fine|penalty)|"
    r"(?:rating )?downgraded?|data breach)\b", re.I)
TAXONOMY = (
    ("EARNINGS", r"\b(?:earnings|quarterly results|profit|revenue)\b"),
    ("GUIDANCE", r"\b(?:guidance|outlook revision)\b"),
    ("ORDER_WIN", r"\b(?:wins? .{0,40}(?:order|contract|tender))\b"),
    ("ORDER_LOSS", r"\b(?:loses? .{0,40}(?:order|contract))\b"),
    ("REGULATORY", r"\b(?:sebi|regulator|regulatory|probe|investigation|fine|penalty)\b"),
    ("LEGAL", r"\b(?:lawsuit|litigation|court|tribunal|settlement)\b"),
    ("MANAGEMENT", r"\b(?:ceo|cfo|chairperson|chairman|resigns?|appoints?)\b"),
    ("MERGER_ACQUISITION", r"\b(?:merger|acquisition|acquires?|takeover|demerger)\b"),
    ("CAPITAL_RAISE", r"\b(?:capital raise|rights issue|qip|share sale)\b"),
    ("DIVIDEND", r"\bdividend\b"),
    ("BUYBACK", r"\bbuyback\b"),
    ("CORPORATE_ACTION", r"\b(?:split|bonus issue|allotment)\b"),
    ("RATING_CHANGE", r"\b(?:upgraded?|downgraded?|rating change)\b"),
    ("ANALYST_RESEARCH", r"\b(?:analyst|brokerage|target price|research note)\b"),
    ("GOVERNMENT_POLICY", r"\b(?:government policy|union budget|new policy)\b"),
    ("SUPPLY_CHAIN", r"\b(?:supply chain|supplier disruption)\b"),
    ("CYBER_SECURITY", r"\b(?:cyber|data breach|ransomware)\b"),
    ("PRODUCT", r"\b(?:launches?|new product|new service)\b"),
    ("SECTOR", r"\b(?:sector|industry)\b"),
    ("MACRO", r"\b(?:inflation|interest rates?|rbi|economy|gdp)\b"),
)
LONG_LIVED = {"EARNINGS", "GUIDANCE", "REGULATORY", "LEGAL", "MERGER_ACQUISITION"}
STOPWORDS = {"the", "and", "for", "with", "from", "after", "about", "india", "stock", "shares", "company"}


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokens(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2 and word not in STOPWORDS}


def _event_type(headline: str, previous: str) -> str:
    for kind, pattern in TAXONOMY:
        if re.search(pattern, headline, re.I):
            return kind
    fallback = {"deal/order": "OTHER", "merger/acquisition": "MERGER_ACQUISITION",
                "analyst/research": "ANALYST_RESEARCH"}
    candidate = fallback.get(previous, previous.upper())
    return candidate if candidate in {name for name, _ in TAXONOMY} else "UNKNOWN"


def analyze_article(article: dict[str, Any], company_name: str, as_of: datetime) -> dict[str, Any]:
    headline = str(article.get("title") or "")
    summary = str(article.get("summary") or "")
    symbol = str(article.get("symbol") or "")
    base = symbol.rsplit(".", 1)[0]
    company = CORPORATE_WORDS.sub("", company_name).strip().lower()
    headline_lower, summary_lower = headline.lower(), summary.lower()
    full_name = bool(company and len(company) >= 7 and company in headline_lower)
    ticker_in_headline = bool(base and re.search(rf"\b{re.escape(base)}\b", headline, re.I))
    context_confirms = bool(company and company in summary_lower)
    relevance = 0.95 if full_name else 0.85 if ticker_in_headline and context_confirms else 0.55 if ticker_in_headline else 0.0
    kind = _event_type(headline, str(article.get("event_type") or ""))
    positive, negative = bool(POSITIVE.search(headline)), bool(NEGATIVE.search(headline))
    direction = "UNCERTAIN" if positive and negative else "POSITIVE" if positive else "NEGATIVE" if negative else "NEUTRAL"
    flags: list[str] = []
    published = _time(article.get("published_at"))
    if published is None or published > as_of:
        flags.append("TIMESTAMP_UNCERTAIN")
        freshness = 0.0
    else:
        hours = (as_of - published).total_seconds() / 3600
        freshness = 1.0 if hours <= 6 else 0.8 if hours <= 24 else 0.6 if hours <= 72 else 0.3 if hours <= 168 else 0.0
        if kind in LONG_LIVED and 72 < hours <= 168:
            freshness = 0.45
        if freshness == 0:
            flags.append("OLD_EVENT")
    if relevance < 0.8:
        flags.append("LOW_RELEVANCE")
    quality = str(article.get("source_quality") or "unrated").lower()
    source_category = quality.upper() if quality in {"high", "medium", "low"} else "UNKNOWN"
    source_score = {"HIGH": 0.8, "MEDIUM": 0.65, "LOW": 0.25, "UNKNOWN": 0.45}[source_category]
    if source_category == "UNKNOWN":
        flags.append("SOURCE_UNCERTAIN")
    elif source_category == "LOW":
        flags.append("SOURCE_LOW")
    if kind == "UNKNOWN":
        flags.append("INSUFFICIENT_CONTEXT")
    if direction == "UNCERTAIN":
        flags.append("CONFLICTING_REPORTS")
    evidence_confidence = 0.8 if full_name and kind != "UNKNOWN" else 0.65 if context_confirms and kind != "UNKNOWN" else 0.45
    uncertainty = round(1 - evidence_confidence, 2)
    eligible = (direction in {"POSITIVE", "NEGATIVE"} and relevance >= 0.8 and freshness > 0
                and kind != "UNKNOWN" and "TIMESTAMP_UNCERTAIN" not in flags)
    strength = round((1 if direction == "POSITIVE" else -1) * relevance * freshness * source_score
                     * evidence_confidence * (1 - uncertainty), 3) if eligible else 0.0
    reason = ("Explicit directional wording in the headline; source-reported, not measured price impact."
              if eligible else "Insufficient verified directional evidence for research-view influence.")
    return {"article_id": article.get("id"), "symbol": symbol, "headline": headline,
            "source": article.get("source"), "url": article.get("url"), "published_at": article.get("published_at"),
            "retrieved_at": article.get("retrieved_at"), "provider": article.get("provenance", {}).get("provider"),
            "event_type": kind, "direction": direction, "relevance": relevance, "freshness": freshness,
            "source_quality": source_category, "source_quality_score": source_score,
            "source_quality_reason": "Publisher/domain heuristic; not an independent source audit." if source_category == "HIGH"
                                     else "Local source-quality category; not an independent source audit.",
            "confidence": evidence_confidence, "uncertainty": uncertainty, "reason": reason,
            "evidence_text": headline, "flags": flags, "impact": strength,
            "provenance": article.get("provenance", {})}


def _same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["event_type"] != right["event_type"] or left["symbol"] != right["symbol"]:
        return False
    a, b = _time(left["published_at"]), _time(right["published_at"])
    if not a or not b or abs((a - b).total_seconds()) > 48 * 3600:
        return False
    if left["url"] == right["url"]:
        return True
    words_a, words_b = _tokens(left["headline"]), _tokens(right["headline"])
    overlap = len(words_a & words_b)
    return overlap >= 3 and (overlap / max(1, len(words_a | words_b)) >= 0.58 or
                             SequenceMatcher(None, left["headline"].lower(), right["headline"].lower()).ratio() >= 0.82)


def assess_news(payload: dict[str, Any], company_name: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc)
    analyzed = []
    for article in payload.get("events", []):
        item = analyze_article(article, company_name, as_of)
        if item["symbol"] != payload.get("symbol"):
            item["impact"] = 0.0
            item["relevance"] = 0.0
            item["flags"] = sorted(set(item["flags"]) | {"LOW_RELEVANCE", "SYMBOL_MISMATCH"})
            item["reason"] = "Article symbol does not match the selected instrument."
        analyzed.append(item)
    groups: list[list[dict[str, Any]]] = []
    for item in analyzed:
        group = next((group for group in groups if _same_event(group[0], item)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    events = []
    for group in groups:
        lead = max(group, key=lambda item: abs(item["impact"]))
        event_id = hashlib.sha256("|".join(sorted(str(item["article_id"]) for item in group)).encode()).hexdigest()[:20]
        flags = {flag for item in group for flag in item["flags"]}
        if len(group) == 1 and lead["source_quality"] != "HIGH":
            flags.add("UNCONFIRMED_EVENT")
        events.append({"event_id": event_id, "event_type": lead["event_type"], "direction": lead["direction"],
                       "impact": lead["impact"], "headline": lead["headline"], "url": lead["url"],
                       "sources": sorted({str(item["source"]) for item in group}),
                       "article_ids": [item["article_id"] for item in group],
                       "flags": sorted(flags)})
    positive = max([0.0, *(event["impact"] for event in events)])
    negative = min([0.0, *(event["impact"] for event in events)])
    current = payload.get("status") in {"FRESH", "NO_EVIDENCE"}
    conflict = current and positive >= 0.12 and negative <= -0.12
    score = round((positive + negative) * (0.5 if conflict else 1.0), 2)
    if not current:
        score = 0.0
    status = "MIXED" if conflict else "POSITIVE" if score >= 0.12 else "NEGATIVE" if score <= -0.12 else "INSUFFICIENT_EVIDENCE"
    if status == "INSUFFICIENT_EVIDENCE":
        score = 0.0
    return {"analysis_version": VERSION, "status": status, "score": score,
            "positive_strength": round(positive, 2), "negative_strength": round(abs(negative), 2),
            "conflict": conflict, "articles_processed": len(analyzed), "events_processed": len(events),
            "qualifying_events": sum(bool(event["impact"]) for event in events) if current else 0,
            "articles": analyzed, "events": events,
            "uncertainty_flags": sorted({flag for item in analyzed for flag in item["flags"]}),
            "interpretation": "Rule-based headline evidence, not measured price impact or predictive accuracy."}


def research_outlook(raw_direction: str, technicals: dict[str, Any] | None,
                     impact: dict[str, Any], *, model_as_of: str | None = None,
                     forecast_ends_at: str | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    direction = "BULLISH" if raw_direction == "up" else "BEARISH" if raw_direction == "down" else "NEUTRAL"
    trend = str((technicals or {}).get("trend") or "unavailable").upper()
    regime = str((technicals or {}).get("regime") or "UNKNOWN")
    aligned = (direction == "BULLISH" and trend == "BULLISH") or (direction == "BEARISH" and trend == "BEARISH")
    opposed = (direction == "BULLISH" and trend == "BEARISH") or (direction == "BEARISH" and trend == "BULLISH")
    baseline = f"MODERATELY_{direction}" if aligned else "NO_STRONG_EDGE"
    view = baseline
    baseline_confidence = "MODERATE" if aligned else "LOW"
    confidence = baseline_confidence
    news_opposes = (direction == "BULLISH" and impact["score"] <= -0.12) or (
        direction == "BEARISH" and impact["score"] >= 0.12)
    news_supports = (direction == "BULLISH" and impact["score"] >= 0.12) or (
        direction == "BEARISH" and impact["score"] <= -0.12)
    if news_opposes or impact["status"] == "MIXED":
        view, confidence = "NO_STRONG_EDGE", "LOW"
    support = [f"Kronos raw direction: {direction.lower()}"]
    contradiction = []
    if aligned:
        support.append(f"Technical trend agrees ({trend.lower()})")
    elif opposed:
        contradiction.append(f"Technical trend opposes Kronos ({trend.lower()})")
    if news_supports:
        support.append("Recent source-linked headline cues agree")
    if news_opposes:
        contradiction.append("Recent source-linked headline cues oppose the raw forecast")
    if impact["status"] == "MIXED":
        contradiction.append("Recent headline cues conflict with each other")
    risk = contradiction[0] if contradiction else ("Matching technical evidence is unavailable or mixed"
                                                 if not aligned else "News is unverified or too weak to change this view"
                                                 if impact["status"] == "INSUFFICIENT_EVIDENCE" else
                                                 "Headline cues are not verified market impact")
    if impact["status"] == "INSUFFICIENT_EVIDENCE":
        why_news = "No verified recent news evidence affecting this research view."
    elif news_opposes:
        why_news = "Recent opposing headline evidence lowers the preliminary view to no strong edge."
    elif impact["status"] == "MIXED":
        why_news = "Conflicting headline evidence lowers the preliminary view to no strong edge."
    else:
        why_news = "Recent headline evidence supports the raw direction but does not change Kronos prices."
    confidence_change = ("LOWER" if confidence != baseline_confidence else
                         "RISK_INCREASED" if news_opposes or impact["status"] == "MIXED" else "UNCHANGED")
    result = {"status": "PRELIMINARY_UNCALIBRATED", "raw_kronos_view": direction,
            "technical_view": trend, "regime": regime, "news_impact": impact["status"],
            "baseline_view": baseline, "preliminary_research_view": view,
            "baseline_confidence": baseline_confidence, "confidence": confidence,
            "confidence_basis": "Qualitative evidence agreement, not a calibrated probability.",
            "confidence_change": confidence_change,
            "max_news_category_change": MAX_OUTLOOK_INFLUENCE, "supporting_evidence": support,
            "contradicting_evidence": contradiction, "primary_risk": risk,
            "why": f"Kronos is {direction.lower()}; technical trend is {trend.lower()}. {why_news}",
            "model_as_of": model_as_of, "analysis_version": VERSION,
            "warning": "Preliminary research context only; news impact has not been historically validated."}
    end = _time(forecast_ends_at)
    if end and (as_of or datetime.now(timezone.utc)) > end + timedelta(minutes=5):
        result.update(status="EXPIRED_FORECAST", preliminary_research_view="NO_STRONG_EDGE",
                      confidence="LOW", confidence_change="UNAVAILABLE",
                      primary_risk="Saved forecast horizon has ended",
                      why="The saved Kronos forecast horizon has ended. Run a new forecast before using a current research outlook.")
    return result


def save_gold(cache_dir: Path, symbol: str, impact: dict[str, Any], outlook: dict[str, Any]) -> dict[str, str]:
    record = {"symbol": symbol, "analysis_version": VERSION, "impact": impact, "research_outlook": outlook}
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = cache_dir / "gold" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        pass
    return {"sha256": digest, "path": str(path.relative_to(cache_dir))}
