"""Immutable, content-addressed evidence joins for preliminary research views."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "evidence_snapshot_v1"


def canonical_bytes(content: dict[str, Any]) -> bytes:
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def snapshot_id(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(content)).hexdigest()


def _news_references(events: list[dict[str, Any]], impact_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Only fields used to interpret the story enter the identity; refresh timestamps and
    # arbitrary provider metadata cannot destabilize it or copy secrets into the snapshot.
    article_fields = ("id", "symbol", "title", "summary", "source", "url", "published_at",
                      "source_quality", "event_type", "relevance", "sentiment")
    event_fields = ("event_id", "event_type", "direction", "impact", "headline", "url",
                    "sources", "article_ids", "flags")
    articles = []
    for event in events:
        if not isinstance(event, dict):
            continue
        reference = {field: event.get(field) for field in article_fields}
        reference["provider"] = (event.get("provenance") or {}).get("provider")
        reference["sha256"] = snapshot_id(reference)
        articles.append(reference)
    return articles, [{field: event.get(field) for field in event_fields}
                      for event in impact_events if isinstance(event, dict)]


def create_content(*, symbol: str, exchange: str, summary: dict[str, Any],
                   fingerprint: str, forecast_sha256: str, input_sha256: str,
                   market: dict[str, Any] | None, technicals: dict[str, Any] | None,
                   news: dict[str, Any], impact: dict[str, Any],
                   outlook: dict[str, Any], news_gold: dict[str, Any] | None = None,
                   technical_version: str | None = None) -> dict[str, Any]:
    matched_market = market if technicals and market and market.get("symbol") == symbol else None
    provenance = (matched_market or {}).get("provenance") or {}
    events = news.get("events") or []
    article_references, impact_references = _news_references(events, impact.get("events") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "instrument": {"canonical_symbol": f"{exchange}:{symbol.rsplit('.', 1)[0]}",
                       "provider_symbol": symbol, "exchange": exchange},
        "market_data": {
            "input_sha256": input_sha256,
            "capture_id": (matched_market or {}).get("capture_id"),
            "bronze_sha256": ((matched_market or {}).get("bronze") or {}).get("sha256"),
            "silver_sha256": ((matched_market or {}).get("silver") or {}).get("sha256"),
            "provider": (matched_market or {}).get("provider") or "unverified_saved_input",
            "retrieved_at": (matched_market or {}).get("retrieved_at"),
            "quality": (matched_market or {}).get("quality", {}).get("state", "UNKNOWN"),
            "cache_status": "hit" if provenance.get("cache_hit") else "miss" if matched_market else "unknown",
        },
        "kronos": {
            "model_id": summary.get("model"), "forecast_fingerprint": fingerprint,
            "forecast_sha256": forecast_sha256,
            "config": {key: summary.get(key) for key in
                       ("input_rows", "forecast_rows", "sampling_T", "sampling_top_k", "sampling_top_p", "sample_count")},
            "direction": summary.get("direction"),
            "last_observed_close": summary.get("last_observed_close"),
            "forecast_final_close": summary.get("forecast_final_close"),
            "forecast_pct_change": summary.get("forecast_pct_change"),
        },
        "technicals": {
            "evidence_reference": ((matched_market or {}).get("gold") or {}).get("sha256") if technicals else None,
            "as_of": (technicals or {}).get("as_of"),
            "values": (technicals or {}).get("indicators"),
            "trend": (technicals or {}).get("trend"),
            "regime": (technicals or {}).get("regime"),
            "version": technical_version if technicals else None,
        },
        "news": {
            "provider": news.get("provider"), "providers_used": news.get("providers_used"),
            "retrieved_at": news.get("retrieved_at"), "cache_status": news.get("cache_status"),
            "bronze_sha256": (news.get("news_pipeline") or {}).get("bronze_hashes", []),
            "gold_sha256": (news_gold or {}).get("sha256"),
            "evidence_status": "GOLD_AVAILABLE" if news_gold else "DEGRADED",
            "article_evidence": article_references,
            "impact_evidence": impact_references,
            "evidence_sha256": snapshot_id({"articles": article_references, "events": impact_references}),
            "event_ids": [event.get("event_id") for event in impact.get("events", [])],
            "article_ids": [event.get("id") for event in events],
            "source_urls": [event.get("url") for event in events],
            "impact_score": impact.get("score"),
            "uncertainty": impact.get("uncertainty_flags", []),
            "formula_version": impact.get("analysis_version"),
        },
        "research_view": {
            "direction": outlook.get("preliminary_research_view"),
            "confidence": {"value": None, "scale": "0_to_1", "calibrated": False,
                           "qualitative_label": outlook.get("confidence")},
            "supporting_evidence": outlook.get("supporting_evidence", []),
            "contradicting_evidence": outlook.get("contradicting_evidence", []),
            "primary_risk": outlook.get("primary_risk"), "why": outlook.get("why"),
            "status": outlook.get("status"), "analysis_version": outlook.get("analysis_version"),
        },
    }


def save_snapshot(root: Path, content: dict[str, Any]) -> dict[str, Any]:
    digest = snapshot_id(content)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    record = {"snapshot_id": digest, "created_at": datetime.now(timezone.utc).isoformat(),
              "evidence": content}
    temporary = root / f".{digest}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("snapshot_id") != digest or existing.get("evidence") != content:
            raise ValueError("Evidence snapshot hash collision or corrupt immutable artifact")
        return existing
    raise OSError("Evidence snapshot was not persisted")


def read_snapshot(root: Path, digest: str) -> dict[str, Any] | None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    try:
        record = json.loads((root / f"{digest}.json").read_text(encoding="utf-8"))
        return record if record.get("snapshot_id") == digest and snapshot_id(record["evidence"]) == digest else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
