"""Deterministic, lineage-aware fusion of existing Kronos Copilot evidence.

The engine consumes immutable EvidenceSnapshotV1 records and optional cached
versioned typed agent reports. It never calls a provider, model, or agent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evidence_snapshot import canonical_bytes, snapshot_id
from app.structured_claims import OUTPUT_SCHEMA_VERSION as AGENT_SCHEMA_VERSION
from app import agent_output_v3 as v3
from app import agent_output_v4 as v4
from app.agent_research import evidence_catalog


FUSION_VERSION = "evidence_fusion_v1"
EVIDENCE_SCHEMA_VERSION = "evidence_item_v1"
OUTPUT_SCHEMA_VERSION = "fusion_output_v1"
LEDGER_SCHEMA_VERSION = "fusion_ledger_v1"

DIRECTION_VALUES = {
    "STRONGLY_BEARISH": -2,
    "BEARISH": -1,
    "NEUTRAL": 0,
    "BULLISH": 1,
    "STRONGLY_BULLISH": 2,
    "UNKNOWN": None,
}
SOURCE_WEIGHTS = {"FORECAST": 1.0, "TECHNICAL": 1.0, "NEWS": 0.75}
QUALITY_FACTORS = {"PASS": 1.0, "WARN": 0.6, "FAIL": 0.0}
FRESHNESS_FACTORS = {"FRESH": 1.0, "AGING": 0.65, "STALE": 0.0, "UNKNOWN": 0.5}
FRESHNESS_WINDOWS_HOURS = {
    "FORECAST": (2, 24),
    "TECHNICAL": (2, 24),
    "NEWS": (72, 168),
    "AGENT": (24, 168),
    "DATA_QUALITY": (2, 24),
}


class EvidenceFusionError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _direction(value: Any) -> str:
    normalized = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "UP": "BULLISH", "POSITIVE": "BULLISH", "TRENDING_BULL": "BULLISH",
        "BULL_CASE": "BULLISH", "MODERATELY_BULLISH": "BULLISH",
        "DOWN": "BEARISH", "NEGATIVE": "BEARISH", "TRENDING_BEAR": "BEARISH",
        "BEAR_CASE": "BEARISH", "MODERATELY_BEARISH": "BEARISH",
        "MIXED": "NEUTRAL", "SIDEWAYS": "NEUTRAL", "NO_STRONG_EDGE": "NEUTRAL",
        "INSUFFICIENT_EVIDENCE": "UNKNOWN", "NO_STRONG_CASE": "UNKNOWN",
        "UNAVAILABLE": "UNKNOWN", "NONE": "UNKNOWN", "": "UNKNOWN",
    }
    result = aliases.get(normalized, normalized)
    return result if result in DIRECTION_VALUES else "UNKNOWN"


def _strength_label(value: float) -> str:
    if value >= 0.67:
        return "HIGH"
    if value >= 0.34:
        return "MEDIUM"
    return "LOW"


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return round(min(1.0, max(0.0, number)), 4) if math.isfinite(number) else default


def _freshness(category: str, observed_at: Any, as_of: datetime) -> str:
    observed = _parse_time(observed_at)
    if observed is None:
        return "UNKNOWN"
    age_hours = max(0.0, (as_of - observed).total_seconds() / 3600)
    fresh, stale = FRESHNESS_WINDOWS_HOURS.get(category, (24, 168))
    return "FRESH" if age_hours <= fresh else "AGING" if age_hours <= stale else "STALE"


def _quality(value: Any, default: str = "WARN") -> str:
    normalized = str(value or default).upper()
    return normalized if normalized in QUALITY_FACTORS else default


def _item(*, evidence_id: str, category: str, role: str, source_component: str,
          symbol: str, observed_at: Any, raw_value: Any, direction: str = "UNKNOWN",
          strength: float = 0.0, quality: str = "PASS", freshness: str = "UNKNOWN",
          provenance: dict[str, Any] | None = None, lineage_ids: list[str] | None = None,
          contributes: bool = False, summary: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    strength = _bounded(strength)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "evidence_type": category,
        "role": role,
        "source_component": source_component,
        "symbol": symbol,
        "observed_at": str(observed_at) if observed_at else None,
        "raw_value": raw_value,
        "direction": _direction(direction),
        "strength": strength,
        "strength_label": _strength_label(strength),
        "confidence_semantics": "RULE_BASED_EVIDENCE_SUPPORT_NOT_PROBABILITY",
        "quality": _quality(quality),
        "freshness": freshness if freshness in FRESHNESS_FACTORS else "UNKNOWN",
        "provenance": provenance or {},
        "lineage_ids": sorted(set(lineage_ids or [evidence_id])),
        "contributes_to_direction": bool(contributes),
        "summary": summary,
        "metadata": metadata or {},
    }


def _technical_strength(technicals: dict[str, Any], direction: str) -> float:
    target = "bullish" if direction == "BULLISH" else "bearish" if direction == "BEARISH" else None
    values = [float(item.get("strength", 0)) for item in technicals.get("values") or []
              if isinstance(item, dict) and str(item.get("signal", "")).lower() == target
              and isinstance(item.get("strength"), (int, float))]
    return _bounded(sum(values) / len(values), 0.35) if values else (0.25 if direction == "NEUTRAL" else 0.35)


def _normalize_snapshot(record: dict[str, Any], as_of: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(record, dict) or not isinstance(record.get("evidence"), dict):
        raise EvidenceFusionError("Evidence snapshot is unavailable")
    content = record["evidence"]
    digest = record.get("snapshot_id")
    if digest != snapshot_id(content):
        raise EvidenceFusionError("Evidence snapshot identity is invalid")
    symbol = str((content.get("instrument") or {}).get("canonical_symbol") or "")
    if not symbol:
        raise EvidenceFusionError("Evidence snapshot has no canonical symbol")

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    market = content.get("market_data") or {}
    market_time = market.get("retrieved_at") or record.get("created_at")
    market_quality = _quality(market.get("quality"), "WARN")
    items.append(_item(
        evidence_id="market_data.quality", category="DATA_QUALITY", role="META",
        source_component="MarketDataService", symbol=symbol, observed_at=market_time,
        raw_value=market.get("quality"), quality=market_quality,
        freshness=_freshness("DATA_QUALITY", market_time, as_of),
        provenance={"provider": market.get("provider"), "input_sha256": market.get("input_sha256"),
                    "bronze_sha256": market.get("bronze_sha256"), "silver_sha256": market.get("silver_sha256"),
                    "cache_status": market.get("cache_status")},
        summary=f"Market data quality is {market_quality.lower()}.",
    ))

    kronos = content.get("kronos") or {}
    forecast_direction = _direction(kronos.get("direction"))
    forecast_identity = kronos.get("forecast_fingerprint") and kronos.get("forecast_sha256")
    if forecast_identity and forecast_direction != "UNKNOWN":
        magnitude = abs(float(kronos.get("forecast_pct_change") or 0))
        strength = _bounded(magnitude / 3.0, 0.35)
        items.append(_item(
            evidence_id="kronos.direction", category="FORECAST", role="PRIMARY",
            source_component="Kronos", symbol=symbol, observed_at=market_time,
            raw_value={"direction": kronos.get("direction"),
                       "forecast_pct_change": kronos.get("forecast_pct_change")},
            direction=forecast_direction, strength=strength, quality=market_quality,
            freshness=_freshness("FORECAST", market_time, as_of),
            provenance={"model_id": kronos.get("model_id"),
                        "forecast_fingerprint": kronos.get("forecast_fingerprint"),
                        "forecast_sha256": kronos.get("forecast_sha256"), "config": kronos.get("config")},
            contributes=True,
            summary=f"Kronos forecast direction is {forecast_direction.lower()}.",
            metadata={"weight": SOURCE_WEIGHTS["FORECAST"],
                      "historical_validation_context": "UNAVAILABLE_IN_EVIDENCE_SNAPSHOT"},
        ))
    else:
        missing.append("KRONOS_FORECAST")

    technicals = content.get("technicals") or {}
    technical_direction = _direction(technicals.get("trend"))
    technical_time = technicals.get("as_of")
    technical_reference = technicals.get("evidence_reference")
    if technical_reference and technical_direction != "UNKNOWN":
        items.append(_item(
            evidence_id="technicals.trend", category="TECHNICAL", role="PRIMARY",
            source_component="TechnicalIntelligence", symbol=symbol, observed_at=technical_time,
            raw_value={"trend": technicals.get("trend"), "indicators": technicals.get("values")},
            direction=technical_direction, strength=_technical_strength(technicals, technical_direction),
            quality=market_quality, freshness=_freshness("TECHNICAL", technical_time, as_of),
            provenance={"gold_sha256": technical_reference, "version": technicals.get("version")},
            contributes=True,
            summary=f"Deterministic technical trend is {technical_direction.lower()}.",
            metadata={"weight": SOURCE_WEIGHTS["TECHNICAL"]},
        ))
        regime_direction = _direction(technicals.get("regime"))
        items.append(_item(
            evidence_id="technicals.regime", category="REGIME", role="PRIMARY",
            source_component="TechnicalIntelligence", symbol=symbol, observed_at=technical_time,
            raw_value=technicals.get("regime"), direction=regime_direction, strength=0.35,
            quality=market_quality, freshness=_freshness("TECHNICAL", technical_time, as_of),
            provenance={"gold_sha256": technical_reference, "version": technicals.get("version")},
            lineage_ids=["technicals.trend", "technicals.regime"], contributes=False,
            summary=f"Market regime is {str(technicals.get('regime') or 'unknown').lower()}.",
            metadata={"deduplication_reason": "Regime is derived from the same technical series."},
        ))
    else:
        missing.append("TECHNICAL_INTELLIGENCE")

    news = content.get("news") or {}
    articles = news.get("article_evidence") or []
    events = news.get("impact_evidence") or []
    news_time = news.get("retrieved_at")
    has_news = bool(news.get("gold_sha256") and news.get("evidence_status") == "GOLD_AVAILABLE")
    if has_news:
        score = float(news.get("impact_score") or 0)
        event_directions = {_direction(event.get("direction")) for event in events if isinstance(event, dict)}
        if score >= 0.12:
            news_direction = "BULLISH"
        elif score <= -0.12:
            news_direction = "BEARISH"
        elif events and event_directions <= {"NEUTRAL", "UNKNOWN"}:
            news_direction = "NEUTRAL"
        else:
            news_direction = "UNKNOWN"
        news_quality = "WARN" if news.get("uncertainty") else "PASS"
        items.append(_item(
            evidence_id="news.impact_score", category="NEWS", role="PRIMARY",
            source_component="NewsImpact", symbol=symbol, observed_at=news_time,
            raw_value={"impact_score": score, "events": events, "articles": articles},
            direction=news_direction, strength=_bounded(abs(score)), quality=news_quality,
            freshness=_freshness("NEWS", news_time, as_of),
            provenance={"provider": news.get("provider"), "providers_used": news.get("providers_used"),
                        "evidence_sha256": news.get("evidence_sha256"),
                        "gold_sha256": news.get("gold_sha256"), "formula_version": news.get("formula_version"),
                        "source_urls": news.get("source_urls")},
            lineage_ids=["news.impact_score", *[f"news.event.{index}" for index in range(len(events))]],
            contributes=news_direction != "UNKNOWN",
            summary=(f"Rule-based news impact is {news_direction.lower()}." if news_direction != "UNKNOWN"
                     else "News is available but has no qualifying directional signal."),
            metadata={"weight": SOURCE_WEIGHTS["NEWS"], "uncertainty": news.get("uncertainty") or [],
                      "interpretation": "Headline context, not measured price impact."},
        ))
        if news_direction == "UNKNOWN":
            missing.append("QUALIFYING_NEWS_SIGNAL")
    else:
        missing.append("NEWS_INTELLIGENCE")

    return items, missing


def _agent_items(agent_result: dict[str, Any] | None, symbol: str, as_of: datetime,
                 catalog: dict[str, Any] | None = None, expected_snapshot: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    agents = (agent_result or {}).get("agents") or {}
    for name in ("bull", "bear", "risk"):
        entry = agents.get(name) or {}
        report = entry.get("report")
        if not isinstance(report, dict):
            missing.append(f"AGENT_{name.upper()}")
            continue
        schema_version = report.get("schema_version", AGENT_SCHEMA_VERSION)
        if schema_version not in {AGENT_SCHEMA_VERSION, "agent_output_v2", v3.SCHEMA_VERSION, v4.SCHEMA_VERSION}:
            missing.append(f"AGENT_{name.upper()}")
            continue
        if schema_version in {v3.SCHEMA_VERSION, v4.SCHEMA_VERSION}:
            try:
                if expected_snapshot != (agent_result or {}).get("snapshot_id"):
                    raise ValueError("Agent snapshot mismatch")
                if schema_version == v3.SCHEMA_VERSION:
                    v3.validate(report, name, expected_snapshot, catalog or {})
                    report = v3.fusion_report(report, catalog or {})
                else:
                    if report.get('snapshot_id') != expected_snapshot or report.get('agent_type') != name:
                        raise ValueError('Agent selection ownership mismatch')
                    report = v4.fusion_report(report, catalog or {})
            except (ValueError, KeyError, TypeError):
                missing.append(f"AGENT_{name.upper()}")
                continue
        analyzed_at = entry.get("analyzed_at")
        if name == "risk":
            direction = "UNKNOWN"
            confidence = _bounded(report.get("confidence_in_risk_assessment"))
            claims = [claim for field in ("risk_factors", "conflicts", "model_risks", "data_risks",
                                            "event_risks", "missing_evidence", "uncertainty", "limitations")
                      for claim in report.get(field, []) if isinstance(claim, dict)]
            raw_label = report.get("risk_level")
            summary = f"Risk Agent reports {str(raw_label or 'unknown').lower()} risk."
        else:
            direction = _direction(report.get("stance"))
            confidence = _bounded(report.get("confidence_in_argument"))
            claims = [claim for field in ("key_factors", "limitations", "uncertainty")
                      for claim in report.get(field, []) if isinstance(claim, dict)]
            if isinstance(report.get("argument"), dict):
                claims.insert(0, report["argument"])
            raw_label = report.get("stance")
            summary = f"{name.title()} Agent presents a {str(raw_label or 'unknown').lower().replace('_', ' ')}."
        lineage = sorted({reference for claim in claims for reference in claim.get("evidence_ids", [])
                          if isinstance(reference, str)})
        items.append(_item(
            evidence_id=f"agent.{name}", category=f"AGENT_{name.upper()}", role="DERIVED",
            source_component=f"{name.title()}Agent", symbol=symbol, observed_at=analyzed_at,
            raw_value={"stance_or_risk": raw_label, "claims": claims}, direction=direction,
            strength=confidence, quality="PASS", freshness=_freshness("AGENT", analyzed_at, as_of),
            provenance={"snapshot_id": (agent_result or {}).get("snapshot_id"),
                        "schema_version": schema_version, "cached": bool(entry.get("cached")),
                        "agent_run_id": entry.get("run_id")},
            lineage_ids=lineage or [f"agent.{name}"], contributes=False, summary=summary,
            metadata={"action": report.get('action'), "confidence_semantics": "argument_support_not_prediction_probability",
                      "deduplication_reason": "Agent output interprets cited primary evidence."},
        ))
    return items, missing


def _pipeline_item(pipeline: dict[str, Any] | None, symbol: str, as_of: datetime) -> dict[str, Any] | None:
    if not pipeline:
        return None
    stages = pipeline.get("stages") or {}
    failures = sorted(name for name, stage in stages.items()
                      if isinstance(stage, dict) and stage.get("status") in {"FAILED", "UNAVAILABLE"})
    warnings = sorted(name for name, stage in stages.items()
                      if isinstance(stage, dict) and stage.get("status") in {"DEGRADED", "STALE"})
    quality = "FAIL" if failures else "WARN" if warnings else "PASS"
    updated = pipeline.get("updated_at")
    return _item(
        evidence_id="pipeline.health", category="DATA_QUALITY", role="META",
        source_component="ProductPipeline", symbol=symbol, observed_at=updated,
        raw_value={"failed_stages": failures, "warning_stages": warnings}, quality=quality,
        freshness=_freshness("DATA_QUALITY", updated, as_of),
        provenance={"schema_version": pipeline.get("schema_version")},
        summary=("Pipeline has failed or unavailable stages." if failures else
                 "Pipeline has degraded or stale stages." if warnings else "Pipeline stages are healthy."),
    )


def _eligible(item: dict[str, Any]) -> bool:
    return (item["role"] == "PRIMARY" and item["contributes_to_direction"] and
            item["direction"] != "UNKNOWN" and item["quality"] != "FAIL" and item["freshness"] != "STALE")


def _conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [item for item in items if _eligible(item) and DIRECTION_VALUES[item["direction"]] != 0]
    conflicts = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1:]:
            if DIRECTION_VALUES[left["direction"]] * DIRECTION_VALUES[right["direction"]] >= 0:
                continue
            pair = sorted([left["evidence_id"], right["evidence_id"]])
            severity = "HIGH" if {left["evidence_type"], right["evidence_type"]} == {"FORECAST", "TECHNICAL"} else "MEDIUM"
            conflicts.append({"conflict_id": _digest({"type": "PRIMARY_DIRECTION", "pair": pair})[:20],
                              "conflict_type": "PRIMARY_DIRECTION_CONFLICT",
                              "evidence_ids": pair, "severity": severity,
                              "explanation": f"{left['source_component']} is {left['direction'].lower()} while {right['source_component']} is {right['direction'].lower()}."})
    bull = next((item for item in items if item["evidence_id"] == "agent.bull" and item["direction"] == "BULLISH"), None)
    bear = next((item for item in items if item["evidence_id"] == "agent.bear" and item["direction"] == "BEARISH"), None)
    if bull and bear:
        pair = ["agent.bear", "agent.bull"]
        conflicts.append({"conflict_id": _digest({"type": "AGENT_INTERPRETATION", "pair": pair})[:20],
                          "conflict_type": "AGENT_INTERPRETATION_CONFLICT", "evidence_ids": pair,
                          "severity": "MEDIUM",
                          "explanation": "Bull and Bear agents present opposing interpretations of shared upstream evidence."})
    return conflicts


def _agreements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [item for item in items if _eligible(item) and DIRECTION_VALUES[item["direction"]] != 0]
    grouped: dict[str, list[str]] = {}
    for item in eligible:
        grouped.setdefault(item["direction"], []).append(item["evidence_id"])
    return [{"agreement_type": "MULTI_SOURCE_ALIGNMENT", "direction": direction,
             "evidence_ids": sorted(ids),
             "explanation": f"{len(ids)} independent primary sources align {direction.lower()}."}
            for direction, ids in sorted(grouped.items()) if len(ids) >= 2]


def _risk(agent_result: dict[str, Any] | None, items: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    risk_report = (((agent_result or {}).get("agents") or {}).get("risk") or {}).get("report") or {}
    if risk_report.get('schema_version', AGENT_SCHEMA_VERSION) not in {AGENT_SCHEMA_VERSION, 'agent_output_v2', v3.SCHEMA_VERSION, v4.SCHEMA_VERSION}:
        risk_report = {}
    if risk_report.get("schema_version") in {v3.SCHEMA_VERSION, v4.SCHEMA_VERSION}:
        validated = next((item for item in items if item['evidence_type'] == 'AGENT_RISK'), None)
        risk_report = ({"risk_level": validated['raw_value']['stance_or_risk'],
                        "risk_factors": validated['raw_value']['claims']} if validated else {})
    level = str(risk_report.get("risk_level") or "UNKNOWN").upper()
    if level not in {"LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN"}:
        level = "UNKNOWN"
    risks = []
    for claim in risk_report.get("risk_factors") or []:
        if isinstance(claim, dict):
            risks.append({"text": claim.get("text"), "risk_level": level,
                          "evidence_ids": claim.get("evidence_ids") or [], "source": "RiskAgent"})
    for conflict in conflicts:
        risks.append({"text": conflict["explanation"], "risk_level": conflict["severity"],
                      "evidence_ids": conflict["evidence_ids"], "source": "EvidenceFusion"})
    if any(item["quality"] == "FAIL" or item["freshness"] == "STALE" for item in items if item["role"] == "PRIMARY"):
        risks.append({"text": "At least one primary evidence source failed quality or freshness gates.",
                      "risk_level": "HIGH", "evidence_ids": [item["evidence_id"] for item in items
                      if item["role"] == "PRIMARY" and (item["quality"] == "FAIL" or item["freshness"] == "STALE")],
                      "source": "EvidenceFusion"})
    if any(item["evidence_id"] == "pipeline.health" and item["quality"] == "FAIL" for item in items):
        risks.append({"text": "One or more operational pipeline stages are unavailable or failed.",
                      "risk_level": "HIGH", "evidence_ids": ["pipeline.health"],
                      "source": "EvidenceFusion"})
    return level, risks


def _assemble(items: list[dict[str, Any]], missing: list[str], agent_result: dict[str, Any] | None) -> dict[str, Any]:
    eligible = [item for item in items if _eligible(item)]
    weighted = []
    for item in eligible:
        direction_value = DIRECTION_VALUES[item["direction"]]
        weight = SOURCE_WEIGHTS.get(item["evidence_type"], 0.0)
        effective = weight * QUALITY_FACTORS[item["quality"]] * FRESHNESS_FACTORS[item["freshness"]]
        directional_strength = item["strength"] if direction_value else 0.0
        weighted.append((item, direction_value, effective, directional_strength))
    denominator = sum(weight for _, _, weight, _ in weighted)
    score = sum((1 if value > 0 else -1 if value < 0 else 0) * strength * weight
                for _, value, weight, strength in weighted) / denominator if denominator else 0.0
    conflicts = _conflicts(items)
    agreements = _agreements(items)
    directional = [row for row in weighted if row[1] != 0]
    insufficient = len(eligible) < 2 or not directional
    if insufficient:
        view = "INSUFFICIENT_EVIDENCE"
    elif abs(score) < 0.25 or (conflicts and abs(score) < 0.5):
        view = "MIXED"
    elif score >= 0.67 and len([row for row in directional if row[1] > 0]) >= 2:
        view = "STRONGLY_BULLISH"
    elif score > 0:
        view = "BULLISH"
    elif score <= -0.67 and len([row for row in directional if row[1] < 0]) >= 2:
        view = "STRONGLY_BEARISH"
    else:
        view = "BEARISH"

    risk_level, risks = _risk(agent_result, items, conflicts)
    agreement_count = max((len(value["evidence_ids"]) for value in agreements), default=0)
    primary_conflicts = [conflict for conflict in conflicts if conflict["conflict_type"] == "PRIMARY_DIRECTION_CONFLICT"]
    operational_failure = any(item["evidence_id"] == "pipeline.health" and item["quality"] == "FAIL" for item in items)
    if view == "INSUFFICIENT_EVIDENCE" or len(eligible) < 2 or primary_conflicts or operational_failure:
        support = "LOW"
    elif agreement_count >= 3 and sum(row[3] for row in directional) / max(1, len(directional)) >= 0.5 and \
            all(item["quality"] == "PASS" and item["freshness"] == "FRESH" for item in eligible):
        support = "HIGH"
    else:
        support = "MEDIUM"
    if risk_level in {"HIGH", "VERY_HIGH"}:
        support = "LOW"
    elif risk_level == "MODERATE" and support == "HIGH":
        support = "MEDIUM"

    primary = [item for item in items if item["role"] == "PRIMARY"]
    if any(item["quality"] == "FAIL" for item in primary):
        evidence_quality = "POOR"
    elif (any(item["quality"] == "WARN" or item["freshness"] in {"AGING", "STALE", "UNKNOWN"} for item in primary)
          or any(value in missing for value in ("KRONOS_FORECAST", "TECHNICAL_INTELLIGENCE", "NEWS_INTELLIGENCE",
                                                 "QUALIFYING_NEWS_SIGNAL", "PIPELINE_HEALTH"))
          or operational_failure):
        evidence_quality = "LIMITED"
    else:
        evidence_quality = "GOOD"

    view_sign = 1 if view in {"BULLISH", "STRONGLY_BULLISH"} else -1 if view in {"BEARISH", "STRONGLY_BEARISH"} else 0
    supporting, opposing = [], []
    for item, value, _, _ in weighted:
        entry = {"evidence_id": item["evidence_id"], "source_component": item["source_component"],
                 "direction": item["direction"], "summary": item["summary"],
                 "lineage_ids": item["lineage_ids"]}
        if view_sign and value * view_sign > 0:
            supporting.append(entry)
        elif value != 0:
            opposing.append(entry)

    source_phrases = [f"{item['source_component']} is {item['direction'].lower()}" for item in eligible]
    if view == "INSUFFICIENT_EVIDENCE":
        explanation = "The system abstains because fewer than two usable primary evidence streams provide a directional basis."
    elif view == "MIXED":
        explanation = "Primary evidence is mixed or too closely balanced for a directional research view."
    else:
        explanation = f"The {view.lower().replace('_', ' ')} research view reflects " + ", ".join(source_phrases) + "."
    if risk_level in {"MODERATE", "HIGH", "VERY_HIGH"}:
        explanation += f" {risk_level.title()} risk lowers the support level without reversing direction."
    if missing:
        explanation += " Missing sources remain explicit and are not treated as neutral evidence."

    return {
        "view": view,
        "support_level": support,
        "evidence_quality": evidence_quality,
        "risk_level": risk_level,
        "summary": explanation,
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "risks": risks,
        "conflicts": conflicts,
        "agreements": agreements,
        "missing_evidence": sorted(set(missing)),
        "aggregation": {"internal_direction_score": round(score, 4),
                        "semantics": "Deterministic ordinal heuristic; not a probability or calibrated accuracy.",
                        "eligible_primary_sources": [item["evidence_id"] for item in eligible]},
    }


class EvidenceFusionEngine:
    """Fuse immutable local evidence with explicit cache and run-ledger identity."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()

    def _cache_key(self, snapshot_digest: str, items: list[dict[str, Any]],
                   agent_result: dict[str, Any] | None) -> str:
        agent_hashes = {name: _digest(entry["report"]) for name, entry in
                        (((agent_result or {}).get("agents") or {}).items())
                        if isinstance(entry, dict) and isinstance(entry.get("report"), dict)}
        identity = {"fusion_version": FUSION_VERSION, "snapshot_id": snapshot_digest,
                    "agent_output_hashes": agent_hashes,
                    "evidence_items_hash": _digest(items)}
        versions = {entry.get('report', {}).get('schema_version')
                    for entry in ((agent_result or {}).get('agents') or {}).values()
                    if isinstance(entry, dict) and isinstance(entry.get('report'), dict)}
        if v4.SCHEMA_VERSION in versions:
            identity['agent_adapter_version'] = v4.VALIDATOR_VERSION
        elif any(entry.get('report', {}).get('schema_version') == v3.SCHEMA_VERSION
               for entry in ((agent_result or {}).get('agents') or {}).values()
               if isinstance(entry, dict) and isinstance(entry.get('report'), dict)):
            identity['agent_adapter_version'] = v3.VALIDATOR_VERSION
        return _digest(identity)

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        try:
            record = json.loads((self.root / "cache" / f"{key}.json").read_text(encoding="utf-8"))
            if record.get("cache_key") != key or record.get("fusion_version") != FUSION_VERSION or \
                    record.get("result_hash") != _digest(record["result"]):
                return None
            return record
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def fuse(self, record: dict[str, Any], *, agent_result: dict[str, Any] | None = None,
             pipeline: dict[str, Any] | None = None, as_of: datetime | None = None) -> dict[str, Any]:
        started = time.monotonic()
        before = canonical_bytes(record)
        agent_before = json.dumps(agent_result, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False) if agent_result is not None else None
        moment = (as_of or _utc_now()).astimezone(timezone.utc)
        items, missing = _normalize_snapshot(record, moment)
        symbol = str(record["evidence"]["instrument"]["canonical_symbol"])
        agent_items, agent_missing = _agent_items(agent_result, symbol, moment, evidence_catalog(record["evidence"]), record['snapshot_id'])
        items.extend(agent_items)
        missing.extend(agent_missing)
        pipeline_item = _pipeline_item(pipeline, symbol, moment)
        if pipeline_item:
            items.append(pipeline_item)
        else:
            missing.append("PIPELINE_HEALTH")

        key = self._cache_key(record["snapshot_id"], items, agent_result)
        run_id = secrets.token_hex(16)
        cached = self._read_cache(key)
        if cached:
            core = copy.deepcopy(cached["result"])
            cache_status = "HIT"
        else:
            assembled = _assemble(items, missing, agent_result)
            lineage = [{"evidence_id": item["evidence_id"], "role": item["role"],
                        "source_component": item["source_component"], "lineage_ids": item["lineage_ids"],
                        "provenance": item["provenance"]} for item in items]
            core = {"schema_version": OUTPUT_SCHEMA_VERSION, "fusion_version": FUSION_VERSION,
                    "symbol": symbol, "snapshot_id": record["snapshot_id"],
                    "generated_at": _iso(moment), **assembled,
                    "evidence_items": items, "source_lineage": lineage,
                    "deduplication": [{"evidence_id": item["evidence_id"],
                                       "reason": item["metadata"].get("deduplication_reason")}
                                      for item in items if item["role"] == "DERIVED" or
                                      item["metadata"].get("deduplication_reason")],
                    "disclaimer": "Research support only; not investment advice. Support is qualitative, not a probability."}
            cache_status = "MISS"

        if before != canonical_bytes(record) or agent_before != (json.dumps(agent_result, sort_keys=True,
                separators=(",", ":"), allow_nan=False) if agent_result is not None else None):
            raise EvidenceFusionError("Fusion modified upstream evidence")

        result_hash = _digest(core)
        latency_ms = int((time.monotonic() - started) * 1000)
        result = {**core, "fusion_run_id": run_id, "result_hash": result_hash,
                  "cache_status": cache_status.lower(), "latency_ms": latency_ms}
        ledger = {"schema_version": LEDGER_SCHEMA_VERSION, "fusion_run_id": run_id,
                  "fusion_version": FUSION_VERSION, "snapshot_id": record["snapshot_id"],
                  "symbol": symbol, "input_evidence_ids": [item["evidence_id"] for item in items],
                  "input_hashes": {"snapshot": record["snapshot_id"], "evidence_state": key},
                  "cache_key": key, "cache_status": cache_status, "output_view": core["view"],
                  "support_level": core["support_level"], "conflicts": core["conflicts"],
                  "missing_evidence": core["missing_evidence"], "evidence_quality": core["evidence_quality"],
                  "result_hash": result_hash, "latency_ms": latency_ms, "created_at": _iso(moment)}
        with self._lock:
            _atomic_json(self.root / "runs" / f"{run_id}.json", ledger)
            if not cached:
                cache_record = {"cache_key": key, "fusion_version": FUSION_VERSION,
                                "result_hash": result_hash, "result": core}
                _atomic_json(self.root / "cache" / f"{key}.json", cache_record)
                ledger["cache_status"] = "STORED"
                _atomic_json(self.root / "runs" / f"{run_id}.json", ledger)
            _atomic_json(self.root / "latest.json", ledger)
        return result

    def health(self) -> dict[str, Any]:
        try:
            latest = json.loads((self.root / "latest.json").read_text(encoding="utf-8"))
            view = latest.get("output_view")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["created_at"])).total_seconds()
            status = "STALE" if age > 3600 or age < 0 else "HEALTHY"
            warnings = []
            if latest.get("missing_evidence"):
                warnings.append("Missing evidence: " + ", ".join(latest["missing_evidence"]))
            if latest.get("conflicts"):
                warnings.append(f"{len(latest['conflicts'])} evidence conflict(s)")
            return {"status": status, "research_view": view, "research_status": "NOT_HISTORICALLY_CALIBRATED",
                    "snapshot_id": latest.get("snapshot_id"), "rows": len(latest.get("input_evidence_ids") or []),
                    "last_update": latest.get("created_at"), "latency_ms": latest.get("latency_ms"),
                    "provider": "local deterministic fusion", "cache_status": str(latest.get("cache_status", "")).lower(),
                    "warnings": warnings, "errors": [], "fusion_run_id": latest.get("fusion_run_id"),
                    "input_completeness": "PARTIAL" if latest.get("missing_evidence") else "COMPLETE",
                    "conflicts": len(latest.get("conflicts") or [])}
        except (OSError, ValueError, TypeError):
            return {"status": "STALE", "rows": 0, "last_update": None, "latency_ms": None,
                    "provider": "local deterministic fusion", "cache_status": "not_applicable",
                    "warnings": ["No fusion run yet"], "errors": [], "input_completeness": "UNKNOWN",
                    "conflicts": 0}

