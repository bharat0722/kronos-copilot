"""Exact, provider-independent bindings for agent facts; no prose entailment."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

OUTPUT_SCHEMA_VERSION = "agent_output_v2_1"
VALIDATOR_VERSION = "structured_claim_grounding_v1"
ALIASES = {"forecast_pct_change": "forecast_return_pct", "forecast_pct": "forecast_return_pct",
           "forecast_percentage": "forecast_return_pct", "forecast_final_close": "forecast_final_price",
           "last_observed_close": "observed_price"}
# Units are native quote units, not an inferred currency. Currency needs explicit cited metadata.
SCALAR_FIELDS = {
    "forecast_direction": ("state", ("kronos.direction",)),
    "forecast_return_pct": ("percent", ("kronos.forecast_pct_change",)),
    "forecast_final_price": ("price", ("kronos.forecast_final_close",)),
    "observed_price": ("price", ("kronos.last_observed_close", "market_data.last_observed_close")),
    "volume": ("volume_units", ("market_data.volume",)),
    "technical_trend": ("state", ("technicals.trend",)),
    "market_regime": ("state", ("technicals.regime",)),
    "news_impact": ("unitless", ("news.impact_score",)),
    "data_quality": ("state", ("market_data.quality",)),
}
INDICATOR_FIELDS = {
    "rsi": (("RSI14",), "unitless"), "macd": (("MACD",), "price"),
    "macd_signal": (("MACD signal", "MACD_SIGNAL"), "price"), "ema20": (("EMA20",), "price"),
    "ema50": (("EMA50",), "price"), "sma20": (("SMA20",), "price"), "sma50": (("SMA50",), "price"),
    "atr": (("ATR14", "ATR"), "price"), "roc": (("ROC10", "ROC"), "percent"),
    "volume_sma": (("Volume SMA20", "VOLUME_SMA"), "volume_units"),
    "volume_spike": (("Volume spike", "VOLUME_SPIKE"), "unitless"),
}
OBJECT_FIELDS = {
    "technical_signal": ("technicals.indicator.", "signal", "state"),
    "technical_strength": ("technicals.indicator.", "strength", "unitless"),
    "news_title": ("news.article.", "title", "text"),
    "news_relevance": ("news.article.", "relevance", "unitless"),
    "news_source_quality": ("news.article.", "source_quality", "unitless"),
    "news_event_headline": ("news.event.", "headline", "text"),
    "news_event_impact": ("news.event.", "impact", "unitless"),
}
FIELD_KEYS = tuple((*SCALAR_FIELDS, *INDICATOR_FIELDS, *OBJECT_FIELDS))
UNITS = ("state", "text", "percent", "price", "unitless", "volume_units", "INR", "USD")
DIRECTIONS = ("up", "down", "upside", "downside")
STRUCTURED_FIELDS = ("field_key", "value", "unit", "direction")


def citable_field_keys(references: tuple[str, ...]) -> list[str]:
    ids = set(references)
    keys = [key for key, (_, allowed) in SCALAR_FIELDS.items() if ids.intersection(allowed)]
    if any(ref.startswith("technicals.indicator.") for ref in ids):
        keys.extend(INDICATOR_FIELDS)
    keys.extend(key for key, (prefix, _, _) in OBJECT_FIELDS.items() if any(ref.startswith(prefix) for ref in ids))
    return [*keys, *(alias for alias, canonical in ALIASES.items() if canonical in keys)]


class StructuredFactError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def field_bindings(field_key: str, references: list[str], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve only explicit fields on cited records, never arbitrary matching leaves."""
    key = ALIASES.get(field_key, field_key)
    bindings = []
    for ref in references:
        source = catalog.get(ref)
        if key in SCALAR_FIELDS:
            unit, allowed = SCALAR_FIELDS[key]
            if ref in allowed and source is not None:
                bindings.append({"field_key": key, "value": source, "unit": unit, "evidence_id": ref})
        elif key in INDICATOR_FIELDS and ref.startswith("technicals.indicator.") and isinstance(source, dict):
            labels, unit = INDICATOR_FIELDS[key]
            if source.get("indicator") in labels and source.get("value") is not None:
                bindings.append({"field_key": key, "value": source["value"], "unit": unit, "evidence_id": ref})
        elif key in OBJECT_FIELDS and isinstance(source, dict):
            prefix, field, unit = OBJECT_FIELDS[key]
            if ref.startswith(prefix) and source.get(field) is not None:
                bindings.append({"field_key": key, "value": source[field], "unit": unit, "evidence_id": ref})
    return bindings


def validate_fact(claim: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    key = claim.get("field_key")
    if not isinstance(key, str) or ALIASES.get(key, key) not in FIELD_KEYS:
        raise StructuredFactError("unsupported_field_key")
    bindings = field_bindings(key, claim["evidence_ids"], catalog)
    if not bindings:
        raise StructuredFactError("field_not_in_cited_evidence")
    value, unit, direction = claim["value"], claim["unit"], claim["direction"]
    if unit not in UNITS or (direction is not None and direction not in DIRECTIONS):
        raise StructuredFactError("invalid_unit_or_direction")
    if claim["support_type"] != "DIRECT" or claim["evidence_type"] == "MULTI_SOURCE":
        raise StructuredFactError("fact_requires_single_family_direct_support")
    if claim["text"] != "":
        raise StructuredFactError("fact_prose_forbidden")
    if claim["claim_type"] == "FACT":
        if not isinstance(value, str) or not value or len(value) > 240 or direction is not None:
            raise StructuredFactError("invalid_state_value")
        if not all(b["unit"] in {"state", "text"} and b["unit"] == unit and b["value"] == value for b in bindings):
            raise StructuredFactError("state_or_unit_mismatch")
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StructuredFactError("invalid_numeric_value")
        number = Decimal(str(value))
        if not number.is_finite():
            raise StructuredFactError("invalid_numeric_value")
        canonical = ALIASES.get(key, key)
        if direction is not None:
            if canonical != "forecast_return_pct" or number == 0:
                raise StructuredFactError("direction_not_applicable")
            if direction in {"down", "downside"}:
                number = -abs(number)
            elif number < 0:
                raise StructuredFactError("sign_direction_mismatch")
        for binding in bindings:
            expected = binding["value"]
            if isinstance(expected, bool) or not isinstance(expected, (int, float)) or not Decimal(str(expected)).is_finite():
                raise StructuredFactError("invalid_numeric_source")
            unit_matches = unit == binding["unit"]
            if unit in {"INR", "USD"} and binding["unit"] == "price":
                prefix = binding["evidence_id"].split(".")[0]
                metadata = f"{prefix}.currency" if prefix == "market_data" else "instrument.currency"
                unit_matches = metadata in claim["evidence_ids"] and catalog.get(metadata) == unit
            if not unit_matches:
                raise StructuredFactError("unit_mismatch")
            if Decimal(str(expected)) != number:
                raise StructuredFactError("value_or_sign_mismatch")
    return bindings


def claim_text(claim: Any) -> str:
    """Display deterministic facts from their validated tuple, not model-written prose."""
    if not isinstance(claim, dict):
        return claim if isinstance(claim, str) else ""
    if claim.get("claim_type") not in {"FACT", "NUMERICAL_FACT"}:
        return claim.get("text", "")
    key = ALIASES.get(claim.get("field_key"), claim.get("field_key"))
    return f"{key} = {claim.get('value')} {claim.get('unit') or ''}{' (' + claim['direction'] + ')' if claim.get('direction') else ''}"
