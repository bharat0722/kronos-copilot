"""Local dashboard server with an optional, cached OpenAI explanation endpoint."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import yfinance as yf
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from forecast_config import (
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_K,
    DEFAULT_TOP_P,
    FORECAST_BARS,
    INTERVAL_MINUTES,
    LOOKBACK_BARS,
    MARKET_TIMEZONE,
    MARKET_TIMEZONE_LABEL,
    SESSION_END,
    SESSION_START,
    coerce_market_timestamps,
    ensure_market_timestamp,
    resolve_forecast_bars,
    trading_duration_label,
)
from first_forecast import FEATURES, MODEL_NAME as KRONOS_MODEL_NAME, build_summary, predict_with_kronos, run_kronos_forecast
from instrument_search import index_stats, search_instruments
from research.market_data import MarketDataRequest
from research.market_data_service import MarketDataError, MarketDataService
from app.product_pipeline import ProductPipeline
from app.news_intelligence import NewsService
from app.news_impact import assess_news, research_outlook, save_gold
from app.security import AccessGuard, EXPENSIVE_POST, LOCAL_READ, PUBLIC_ASSETS, is_loopback, local_secret, same_origin, valid_host
from app.evidence_snapshot import create_content, read_snapshot, save_snapshot
from app.agent_research import AgentConfig, AgentError, AgentTeam

SUMMARY_PATH = PROJECT_ROOT / "outputs" / "forecast_summary.json"
CACHE_PATH = PROJECT_ROOT / "outputs" / "explanation.json"
ENV_PATH = PROJECT_ROOT / ".env.local"
UPLOADED_DATA_PATH = PROJECT_ROOT / "data" / "uploaded_market_data.csv"
FORECAST_SCRIPT = PROJECT_ROOT / "src" / "first_forecast.py"
FORECAST_PATH = PROJECT_ROOT / "outputs" / "forecast.csv"
VALIDATION_ACTUAL_PATH = PROJECT_ROOT / "outputs" / "validation_actual.csv"
FORECAST_CACHE_DIR = PROJECT_ROOT / "outputs" / "forecast_cache"
MODEL_NAME = "gpt-5-mini"
EXPLANATION_PROMPT_VERSION = "3"
FORECAST_LOCK = threading.Lock()
EXPLANATION_LOCK = threading.Lock()
REQUIRED_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]
SYMBOL_SEARCH_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, str]]]] = {}
SYMBOL_SEARCH_TTL_SECONDS = 300
LIVE_MARKET_DATA_SERVICE = MarketDataService()
PRODUCT_PIPELINE = ProductPipeline(PROJECT_ROOT / "outputs" / "pipeline")
NEWS_SERVICE = NewsService(PROJECT_ROOT / "outputs" / "news_cache")
ACCESS_GUARD = AccessGuard(ENV_PATH)
EVIDENCE_DIR = PROJECT_ROOT / "outputs" / "evidence_snapshots"
AGENT_TEAM = AgentTeam(PROJECT_ROOT / "outputs" / "agent_research", config=AgentConfig(model=MODEL_NAME))


def load_local_key() -> None:
    """Load the local key without placing it in browser-visible code."""
    if os.environ.get("OPENAI_API_KEY") or not ENV_PATH.exists():
        return

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
            return


def current_agent_snapshot(digest: str) -> dict[str, object]:
    """Only the current saved, unchanged product forecast may be analyzed."""
    record = read_snapshot(EVIDENCE_DIR, digest)
    if not record:
        raise AgentError("SNAPSHOT_NOT_FOUND", "Evidence snapshot not found.")
    evidence = record["evidence"]
    try:
        summary = load_summary()
        matches = (evidence["kronos"]["forecast_fingerprint"] == summary_fingerprint(summary) and
                   evidence["kronos"]["forecast_sha256"] == hashlib.sha256(FORECAST_PATH.read_bytes()).hexdigest() and
                   evidence["market_data"]["input_sha256"] == hashlib.sha256(UPLOADED_DATA_PATH.read_bytes()).hexdigest())
    except (KeyError, OSError, ValueError, TypeError):
        matches = False
    if not matches:
        raise AgentError("STALE_SNAPSHOT", "Evidence changed. Refresh the research view before running agents.")
    return record


def load_summary() -> dict[str, object]:
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError("Run the local Kronos forecast before requesting an explanation.")
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def forecast_identity(summary: dict[str, object]) -> dict[str, object]:
    """Return the stable fields that bind an explanation to one exact forecast."""
    input_source = str(summary.get("input_source", ""))
    _, normalized_symbol, exchange, source_type = source_identity(input_source)
    history = pd.read_csv(UPLOADED_DATA_PATH) if UPLOADED_DATA_PATH.exists() else pd.DataFrame()
    timestamps = (
        coerce_market_timestamps(history.get("timestamps")).dropna()
        if "timestamps" in history
        else pd.Series(dtype="datetime64[ns]")
    )
    last_observed_timestamp = timestamps.iloc[-1].isoformat() if not timestamps.empty else ""
    forecast = pd.read_csv(FORECAST_PATH) if FORECAST_PATH.exists() else pd.DataFrame()
    forecast_timestamps = (
        coerce_market_timestamps(forecast.get("timestamps")).dropna()
        if "timestamps" in forecast
        else pd.Series(dtype="datetime64[ns]")
    )
    forecast_hash = (
        hashlib.sha256(FORECAST_PATH.read_bytes()).hexdigest()
        if FORECAST_PATH.exists()
        else ""
    )
    return {
        "normalized_symbol": normalized_symbol,
        "exchange": exchange or "CSV",
        "data_source": source_type,
        "interval_minutes": INTERVAL_MINUTES,
        "last_observed_timestamp": last_observed_timestamp,
        "first_forecast_timestamp": forecast_timestamps.iloc[0].isoformat() if not forecast_timestamps.empty else "",
        "final_forecast_timestamp": forecast_timestamps.iloc[-1].isoformat() if not forecast_timestamps.empty else "",
        "forecast_count": int(summary.get("forecast_rows", 0) or 0),
        "forecast_version": datetime.fromtimestamp(
            SUMMARY_PATH.stat().st_mtime, tz=timezone.utc
        ).isoformat() if SUMMARY_PATH.exists() else "",
        "kronos_model": summary.get("model"),
        "last_observed_price": summary.get("last_observed_close"),
        "final_forecast_price": summary.get("forecast_final_close"),
        "movement_percentage": summary.get("forecast_pct_change"),
        "forecast_low": summary.get("forecast_min_close"),
        "forecast_high": summary.get("forecast_max_close"),
        "direction": summary.get("direction"),
        "forecast_output_hash": forecast_hash,
        "explanation_prompt_version": EXPLANATION_PROMPT_VERSION,
    }


def summary_fingerprint(summary: dict[str, object]) -> str:
    serialized = json.dumps(forecast_identity(summary), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compact_explanation_summary(summary: dict[str, object]) -> dict[str, object]:
    identity = forecast_identity(summary)
    last_price = float(summary.get("last_observed_close", 0) or 0)
    range_span = float(summary.get("forecast_max_close", 0) or 0) - float(
        summary.get("forecast_min_close", 0) or 0
    )
    compact = {
        "symbol": identity["normalized_symbol"],
        "exchange": identity["exchange"],
        "data_source": identity["data_source"],
        "currency": "INR" if identity["exchange"] in {"NSE", "BSE"} else "unspecified",
        "interval_minutes": identity["interval_minutes"],
        "observed_bars": summary.get("input_rows"),
        "forecast_horizon": summary.get("forecast_horizon_label", "Next 75 market bars"),
        "forecast_bars": summary.get("forecast_rows"),
        "last_observed_timestamp": identity["last_observed_timestamp"],
        "forecast_start": identity["first_forecast_timestamp"],
        "forecast_end": identity["final_forecast_timestamp"],
        "last_observed_price": identity["last_observed_price"],
        "final_forecast_price": identity["final_forecast_price"],
        "movement_percentage": identity["movement_percentage"],
        "direction": identity["direction"],
        "forecast_low": identity["forecast_low"],
        "forecast_high": identity["forecast_high"],
        "forecast_range_percent_of_last": round(range_span / last_price * 100, 4) if last_price else None,
        "forecast_close_std": summary.get("forecast_close_std"),
        "forecast_range_pct": summary.get("forecast_range_pct"),
        "sampling_T": summary.get("sampling_T"),
        "sampling_top_p": summary.get("sampling_top_p"),
        "sample_count": summary.get("sample_count"),
        "inference_time_seconds": summary.get("inference_time_seconds"),
        "kronos_model": identity["kronos_model"],
        "forecast_timestamp": identity["forecast_version"],
    }
    if summary.get("mode") == "validation":
        compact.update({
            "validation_mode": True,
            "actual_final_price": summary.get("actual_final_close"),
            "actual_movement_percentage": summary.get("actual_pct_change"),
            "mae": summary.get("mae"),
            "rmse": summary.get("rmse"),
            "final_error_pct": summary.get("final_error_pct"),
            "directional_match": summary.get("directional_match"),
            "directional_agreement_pct": summary.get("directional_agreement_pct"),
        })
    return compact


def load_cached_explanation(summary: dict[str, object]) -> dict[str, object] | None:
    if not CACHE_PATH.exists():
        return None
    cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if (
        cached.get("summary_fingerprint") == summary_fingerprint(summary)
        and cached.get("prompt_version") == EXPLANATION_PROMPT_VERSION
    ):
        return cached
    return None


def format_explanation_currency(explanation: str, summary: dict[str, object]) -> str:
    """Use polished currency notation only when the market identity is known."""
    _, _, exchange, _ = source_identity(str(summary.get("input_source", "")))
    if exchange not in {"NSE", "BSE"}:
        return explanation
    formatted = re.sub(r"\bINR\s*([0-9][0-9,]*(?:\.[0-9]+)?)", r"₹\1", explanation)
    formatted = re.sub(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*INR\b", r"₹\1", formatted)
    return re.sub(r"(?<![₹0-9])([0-9][0-9,]*(?:\.[0-9]+)?)([–-])(?=₹)", r"₹\1\2", formatted)


def generate_explanation(requested_fingerprint: str | None = None) -> dict[str, object]:
    with EXPLANATION_LOCK:
        return _generate_explanation(requested_fingerprint)


def _generate_explanation(requested_fingerprint: str | None = None) -> dict[str, object]:
    summary = load_summary()
    current_fingerprint = summary_fingerprint(summary)
    if requested_fingerprint and requested_fingerprint != current_fingerprint:
        raise RuntimeError("This explanation no longer matches the current forecast.")
    cached = load_cached_explanation(summary)
    if cached:
        return {
            "explanation": format_explanation_currency(cached["explanation"], summary),
            "cached": True,
            "model": cached["model"],
            "summary_fingerprint": current_fingerprint,
        }

    load_local_key()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("A local OpenAI API key is required for this optional feature.")

    explanation_summary = compact_explanation_summary(summary)

    client = OpenAI()
    response = client.responses.create(
        model=MODEL_NAME,
        instructions=(
            "Explain this compact Kronos-base forecast in 90-120 plain-language words. "
            "Include direction, percentage movement, range, practical meaning, and one uncertainty sentence. "
            "State that Kronos-base generated the forecast locally and that it is not investment advice. "
            "Do not add market facts, recommendations, or claims beyond the supplied JSON. "
            "When currency is INR, use the rupee symbol ₹ instead of the letters INR. "
            "When currency is unspecified, "
            "do not add any currency name or symbol."
        ),
        input=json.dumps(explanation_summary, separators=(",", ":")),
        reasoning={"effort": "minimal"},
        text={"verbosity": "low"},
        max_output_tokens=180,
    )
    explanation = format_explanation_currency(response.output_text.strip(), summary)
    if summary_fingerprint(load_summary()) != current_fingerprint:
        raise RuntimeError("The forecast changed while the explanation was being created.")
    result = {
        "summary_fingerprint": current_fingerprint,
        "prompt_version": EXPLANATION_PROMPT_VERSION,
        "explanation": explanation,
        "model": MODEL_NAME,
    }
    CACHE_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {
        "explanation": explanation,
        "cached": False,
        "model": MODEL_NAME,
        "summary_fingerprint": current_fingerprint,
    }


def validate_market_csv(csv_text: str) -> pd.DataFrame:
    """Return a readable market frame with beginner-friendly validation errors."""
    try:
        market_data = pd.read_csv(io.StringIO(csv_text))
    except Exception as error:
        raise ValueError("This CSV could not be read. Export it as a standard comma-separated file and try again.") from error

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in market_data.columns]
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing_columns)}.")
    valid_rows = market_data[REQUIRED_COLUMNS].dropna()
    if len(valid_rows) < LOOKBACK_BARS:
        raise ValueError(f"Kronos needs {LOOKBACK_BARS} valid market bars. This source returned {len(valid_rows)}.")
    return market_data


def normalize_market_data(market_data: pd.DataFrame) -> pd.DataFrame:
    clean_data = market_data[REQUIRED_COLUMNS].dropna().copy()
    clean_data["timestamps"] = coerce_market_timestamps(clean_data["timestamps"])
    return clean_data.sort_values("timestamps").drop_duplicates("timestamps").reset_index(drop=True)


def forecast_cache_key(
    market_data: pd.DataFrame,
    *,
    mode: str,
    input_label: str,
    forecast_bars: int,
    temperature: float = DEFAULT_TEMPERATURE,
    top_k: int = DEFAULT_TOP_K,
    top_p: float = DEFAULT_TOP_P,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> str:
    normalized = normalize_market_data(market_data)
    stable_data = pd.DataFrame({
        "timestamps": normalized["timestamps"].map(iso_timestamp),
        "open": normalized["open"].astype(float).round(6),
        "high": normalized["high"].astype(float).round(6),
        "low": normalized["low"].astype(float).round(6),
        "close": normalized["close"].astype(float).round(6),
        "volume": normalized["volume"].astype(float).round(3),
        "amount": normalized["amount"].astype(float).round(3),
    })
    data_hash = hashlib.sha256(stable_data.to_csv(index=False).encode("utf-8")).hexdigest()
    identity = {
        "mode": mode,
        "input_label": input_label,
        "data_hash": data_hash,
        "last_timestamp": iso_timestamp(normalized["timestamps"].iloc[-1]) if not normalized.empty else "",
        "lookback": LOOKBACK_BARS,
        "prediction_length": forecast_bars,
        "model": KRONOS_MODEL_NAME,
        "T": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "sample_count": sample_count,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cache_paths(key: str) -> tuple[Path, Path, Path]:
    directory = FORECAST_CACHE_DIR / key
    return directory / "forecast.csv", directory / "summary.json", directory / "validation_actual.csv"


def restore_forecast_cache(key: str, validation: bool = False) -> dict[str, object] | None:
    forecast_cache, summary_cache, actual_cache = cache_paths(key)
    if not forecast_cache.exists() or not summary_cache.exists():
        return None
    FORECAST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(forecast_cache, FORECAST_PATH)
    shutil.copy2(summary_cache, SUMMARY_PATH)
    if validation and actual_cache.exists():
        shutil.copy2(actual_cache, VALIDATION_ACTUAL_PATH)
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    summary["cache_hit"] = True
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def save_forecast_cache(key: str, validation: bool = False) -> None:
    directory = FORECAST_CACHE_DIR / key
    directory.mkdir(parents=True, exist_ok=True)
    forecast_cache, summary_cache, actual_cache = cache_paths(key)
    if FORECAST_PATH.exists():
        shutil.copy2(FORECAST_PATH, forecast_cache)
    if SUMMARY_PATH.exists():
        shutil.copy2(SUMMARY_PATH, summary_cache)
    if validation and VALIDATION_ACTUAL_PATH.exists():
        shutil.copy2(VALIDATION_ACTUAL_PATH, actual_cache)


def validation_metrics(predicted: pd.DataFrame, actual: pd.DataFrame, context: pd.DataFrame) -> dict[str, object]:
    joined = predicted[["timestamps", "close"]].rename(columns={"close": "predicted_close"}).merge(
        actual[["timestamps", "close"]].rename(columns={"close": "actual_close"}),
        on="timestamps",
        how="inner",
    )
    if joined.empty:
        raise ValueError("Validation could not align predicted bars with the hidden actual future bars.")
    error = joined["predicted_close"] - joined["actual_close"]
    mae = float(error.abs().mean())
    rmse = float((error.pow(2).mean()) ** 0.5)
    actual_final = float(joined["actual_close"].iloc[-1])
    predicted_final = float(joined["predicted_close"].iloc[-1])
    context_final = float(context["close"].iloc[-1])
    actual_move = actual_final - context_final
    predicted_move = predicted_final - context_final
    actual_direction = "up" if actual_move >= 0 else "down"
    predicted_direction = "up" if predicted_move >= 0 else "down"
    actual_steps = joined["actual_close"].diff().iloc[1:]
    predicted_steps = joined["predicted_close"].diff().iloc[1:]
    step_mask = actual_steps.ne(0) & predicted_steps.ne(0)
    directional_agreement = None
    if step_mask.any():
        directional_agreement = round(float((actual_steps[step_mask].gt(0) == predicted_steps[step_mask].gt(0)).mean() * 100), 2)
    return {
        "mode": "validation",
        "actual_rows": int(len(actual)),
        "compared_rows": int(len(joined)),
        "actual_final_close": round(actual_final, 4),
        "actual_pct_change": round((actual_final - context_final) / context_final * 100, 3) if context_final else None,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(float((error.abs() / joined["actual_close"].abs()).mean() * 100), 4) if (joined["actual_close"].abs() > 0).all() else None,
        "final_error_pct": round(abs(predicted_final - actual_final) / actual_final * 100, 4) if actual_final else None,
        "directional_match": predicted_direction == actual_direction,
        "actual_direction": actual_direction,
        "predicted_direction": predicted_direction,
        "directional_agreement_pct": directional_agreement,
    }


def run_validation(
    csv_text: str,
    input_label: str = "uploaded_market_data.csv",
    request_id: int | str | None = None,
    forecast_bars: int | str | None = None,
) -> dict[str, object]:
    if not csv_text.strip():
        raise ValueError("Select a CSV file before starting validation.")
    market_data = normalize_market_data(validate_market_csv(csv_text))
    forecast_bars = resolve_forecast_bars(forecast_bars)
    cache_key = forecast_cache_key(
        market_data,
        mode="validation",
        input_label=input_label,
        forecast_bars=forecast_bars,
    )
    required = LOOKBACK_BARS + forecast_bars
    if len(market_data) < required:
        raise ValueError(f"Validation needs {required} valid market bars: {LOOKBACK_BARS} context bars plus {forecast_bars} hidden future bars.")
    context = market_data.iloc[-required:-forecast_bars].reset_index(drop=True)
    actual = market_data.iloc[-forecast_bars:].reset_index(drop=True)

    with FORECAST_LOCK:
        cached_summary = restore_forecast_cache(cache_key, validation=True)
        if cached_summary:
            return build_dashboard_payload(cached_summary, context, request_id)
        UPLOADED_DATA_PATH.write_text(market_data.to_csv(index=False), encoding="utf-8")
        forecast, inference_seconds = predict_with_kronos(
            context,
            actual["timestamps"],
            forecast_bars,
            temperature=DEFAULT_TEMPERATURE,
            top_k=DEFAULT_TOP_K,
            top_p=DEFAULT_TOP_P,
            sample_count=DEFAULT_SAMPLE_COUNT,
        )
        forecast.to_csv(FORECAST_PATH, index=False)
        actual.to_csv(VALIDATION_ACTUAL_PATH, index=False)
        summary = build_summary(
            context,
            forecast,
            f"{Path(input_label).name} validation",
            forecast_bars=forecast_bars,
            temperature=DEFAULT_TEMPERATURE,
            top_k=DEFAULT_TOP_K,
            top_p=DEFAULT_TOP_P,
            sample_count=DEFAULT_SAMPLE_COUNT,
            inference_seconds=inference_seconds,
        )
        summary.update(validation_metrics(forecast, actual, context))
        summary["cache_hit"] = False
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        save_forecast_cache(cache_key, validation=True)
        payload = build_dashboard_payload(summary, context, request_id)
        return payload


def source_identity(input_source: str) -> tuple[str, str, str | None, str]:
    live_match = re.match(r"^([A-Z0-9.^=\-]+)\.(NS|BO) live", input_source, re.IGNORECASE)
    if live_match:
        normalized_symbol = f"{live_match.group(1).upper()}.{live_match.group(2).upper()}"
        exchange = "NSE" if normalized_symbol.endswith(".NS") else "BSE"
        return normalized_symbol.split(".", 1)[0], normalized_symbol, exchange, "live"
    display_name = Path(input_source).stem or "CSV forecast"
    return display_name, display_name, None, "csv"


def normalize_exchange(value: str) -> str:
    exchange = value.strip().upper()
    return exchange if exchange in {"NSE", "BSE"} else "NSE"


def result_exchange(symbol: str, quote: dict[str, object]) -> str | None:
    upper_symbol = symbol.upper()
    exchange_hint = str(quote.get("exchange") or quote.get("exchDisp") or "").upper()
    if upper_symbol.endswith(".NS") or exchange_hint in {"NSE", "NSI"}:
        return "NSE"
    if upper_symbol.endswith(".BO") or exchange_hint in {"BSE", "BOM", "BSE LTD"}:
        return "BSE"
    return None


def normalize_symbol_result(quote: dict[str, object]) -> dict[str, str] | None:
    symbol = str(quote.get("symbol") or "").strip().upper()
    exchange = result_exchange(symbol, quote)
    quote_type = str(quote.get("quoteType") or quote.get("typeDisp") or "").lower()
    if not symbol or exchange not in {"NSE", "BSE"}:
        return None
    if quote_type and quote_type not in {"equity", "stock"}:
        return None
    if not re.fullmatch(r"[A-Z0-9.^=\-]+(\.NS|\.BO)", symbol):
        return None
    name = str(
        quote.get("longname")
        or quote.get("shortname")
        or quote.get("name")
        or symbol
    ).strip()
    return {
        "symbol": symbol,
        "baseSymbol": symbol.rsplit(".", 1)[0],
        "name": name,
        "exchange": exchange,
        "type": "Equity",
    }


def direct_symbol_result(query: str, preferred_exchange: str) -> dict[str, str] | None:
    clean = query.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=\-]{1,20}(\.(NS|BO))?", clean):
        return None
    if clean.endswith((".NS", ".BO")):
        symbol = clean
        exchange = "NSE" if clean.endswith(".NS") else "BSE"
    else:
        exchange = preferred_exchange
        symbol = f"{clean}{'.NS' if exchange == 'NSE' else '.BO'}"
    return {
        "symbol": symbol,
        "baseSymbol": symbol.rsplit(".", 1)[0],
        "name": symbol.rsplit(".", 1)[0],
        "exchange": exchange,
        "type": "Equity",
    }


def search_score(result: dict[str, str], query: str, preferred_exchange: str) -> tuple[int, str]:
    compact_query = re.sub(r"\s+", " ", query.strip().upper())
    name = result["name"].upper()
    symbol = result["symbol"].upper()
    base = result["baseSymbol"].upper()
    score = 0
    if result["exchange"] == preferred_exchange:
        score -= 20
    if compact_query == symbol:
        score -= 100
    elif compact_query == base:
        score -= 90
    elif compact_query == name:
        score -= 80
    elif symbol.startswith(compact_query) or base.startswith(compact_query):
        score -= 70
    elif name.startswith(compact_query):
        score -= 60
    elif compact_query in name:
        score -= 40
    return score, result["symbol"]


def symbol_search(query: str, exchange: str) -> list[dict[str, str]]:
    cleaned = re.sub(r"\s+", " ", query.strip())
    preferred_exchange = normalize_exchange(exchange)
    if len(cleaned) < 2:
        return []
    cache_key = (cleaned.lower(), preferred_exchange)
    cached = SYMBOL_SEARCH_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < SYMBOL_SEARCH_TTL_SECONDS:
        return cached[1]

    results: list[dict[str, str]] = []
    local_results = search_instruments(cleaned, preferred_exchange, limit=8)
    results.extend(local_results)

    direct = direct_symbol_result(cleaned, preferred_exchange)
    if direct and (cleaned.upper().endswith((".NS", ".BO")) or not local_results):
        results.append(direct)

    if len(results) < 4 and len(re.sub(r"[^A-Za-z0-9]", "", cleaned)) >= 3:
        try:
            search = yf.Search(
                cleaned,
                max_results=12,
                news_count=0,
                lists_count=0,
                include_research=False,
                include_cultural_assets=False,
                timeout=5,
                raise_errors=False,
            )
            for quote in search.quotes or []:
                normalized = normalize_symbol_result(quote)
                if normalized:
                    results.append(normalized)
        except Exception:
            pass

    unique: dict[str, dict[str, str]] = {}
    for result in results:
        existing = unique.get(result["symbol"])
        if not existing or len(str(result.get("name", ""))) > len(str(existing.get("name", ""))):
            unique[result["symbol"]] = result
    ranked = list(unique.values())[:10]
    SYMBOL_SEARCH_CACHE[cache_key] = (time.time(), ranked)
    return ranked


def iso_timestamp(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return ensure_market_timestamp(parsed).isoformat()


def market_point(row: pd.Series) -> dict[str, object]:
    point: dict[str, object] = {"timestamp": iso_timestamp(row["timestamps"])}
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in row and pd.notna(row[column]):
            point[column] = float(row[column])
    return point


def is_market_open(now: pd.Timestamp) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return SESSION_START <= current < SESSION_END


def format_ist_timestamp(timestamp: pd.Timestamp) -> str:
    return ensure_market_timestamp(timestamp).strftime("%d %b %Y, %I:%M %p IST").replace(" 0", " ")


def freshness_message(latest_bar: pd.Timestamp | None, source_type: str) -> str:
    if source_type != "live" or latest_bar is None:
        return "CSV forecast · Timestamp quality depends on the uploaded file."
    now = pd.Timestamp.now(tz=MARKET_TIMEZONE)
    latest = ensure_market_timestamp(latest_bar)
    if not is_market_open(now):
        return f"Market closed · Last available bar {format_ist_timestamp(latest)}"
    age_minutes = max(int((now - latest).total_seconds() // 60), 0)
    if age_minutes > 20:
        return f"Yahoo Finance · Latest bar is {age_minutes} minutes old · Market data may be delayed"
    return "Yahoo Finance · Recent five-minute market data · Market data may be delayed"


def build_dashboard_payload(
    summary: dict[str, object],
    history: pd.DataFrame | None = None,
    request_id: int | str | None = None,
) -> dict[str, object]:
    """Add UI metadata and chart points without changing forecast calculations."""
    if history is None and UPLOADED_DATA_PATH.exists():
        history = pd.read_csv(UPLOADED_DATA_PATH)
    if history is None:
        history = pd.DataFrame(columns=REQUIRED_COLUMNS)

    forecast = pd.read_csv(FORECAST_PATH) if FORECAST_PATH.exists() else pd.DataFrame()
    history = history.copy()
    if "timestamps" in history:
        history["timestamps"] = coerce_market_timestamps(history["timestamps"])
    valid_history = history.dropna(subset=["timestamps", "close"]).tail(64)
    ema_context = history.dropna(subset=["timestamps", "close"]).tail(LOOKBACK_BARS).copy()
    if not ema_context.empty:
        ema_context["close"] = pd.to_numeric(ema_context["close"])
        for span in (20, 50):
            ema_context[f"ema{span}"] = ema_context["close"].ewm(span=span, adjust=False).mean()
    ema_visible = ema_context.tail(len(valid_history))

    if not forecast.empty:
        forecast = forecast.copy()
        forecast["timestamps"] = coerce_market_timestamps(forecast.get("timestamps"))

    input_source = str(summary.get("input_source", "Unknown source"))
    display_symbol, normalized_symbol, exchange, source_type = source_identity(input_source)
    observed_points = [market_point(row) for _, row in valid_history.iterrows()]
    forecast_points = [market_point(row) for _, row in forecast.dropna(subset=["timestamps", "close"]).iterrows()]
    actual_points: list[dict[str, object]] = []
    if summary.get("mode") == "validation" and VALIDATION_ACTUAL_PATH.exists():
        actual_data = pd.read_csv(VALIDATION_ACTUAL_PATH)
        if "timestamps" in actual_data:
            actual_data["timestamps"] = coerce_market_timestamps(actual_data["timestamps"])
            actual_points = [
                market_point(row)
                for _, row in actual_data.dropna(subset=["timestamps", "close"]).iterrows()
            ]
    all_history_timestamps = history.dropna(subset=["timestamps"])["timestamps"] if "timestamps" in history else pd.Series(dtype="datetime64[ns]")
    latest_market_bar = all_history_timestamps.iloc[-1] if not all_history_timestamps.empty else None
    forecast_created_at = pd.Timestamp.fromtimestamp(SUMMARY_PATH.stat().st_mtime, tz=MARKET_TIMEZONE).isoformat()
    yahoo_retrieved_at = str(summary.get("yahoo_retrieved_at", "")) or None
    data_source_name = (
        "Yahoo Finance · Recent five-minute market data"
        if source_type == "live"
        else "Uploaded CSV market data"
    )
    payload = dict(summary)
    payload.update(
        {
            "display_symbol": display_symbol,
            "normalized_symbol": normalized_symbol,
            "exchange": exchange,
            "source_type": source_type,
            "currency": "INR" if exchange in {"NSE", "BSE"} else None,
            "interval_minutes": INTERVAL_MINUTES,
            "interval_label": "Each point = 5 minutes",
            "forecast_created_at": forecast_created_at,
            "data_source_name": data_source_name,
            "market_freshness": freshness_message(latest_market_bar, source_type),
            "exchange_holiday_note": "Projected trading timestamps may not account for every exchange holiday.",
            "summary_fingerprint": summary_fingerprint(summary),
            "chart": {
                "observed": observed_points,
                "forecast": forecast_points,
                "actual": actual_points,
                "analytical_ema": {
                    f"ema{span}": [{"timestamp": iso_timestamp(row["timestamps"]), "value": float(row[f"ema{span}"])}
                                    for _, row in ema_visible.iterrows()]
                    for span in (20, 50)
                },
            },
            "validation": {
                **{key: summary.get(key) for key in (
                    "actual_rows", "compared_rows", "actual_final_close", "actual_pct_change",
                    "mae", "rmse", "mape", "final_error_pct", "directional_match",
                    "actual_direction", "predicted_direction", "directional_agreement_pct"
                )},
                "actual": actual_points,
            } if summary.get("mode") == "validation" else None,
            "timing": {
                "observed_start": observed_points[0]["timestamp"] if observed_points else "",
                "observed_end": observed_points[-1]["timestamp"] if observed_points else "",
                "last_yahoo_market_bar": iso_timestamp(latest_market_bar) if latest_market_bar is not None else "",
                "first_forecast_timestamp": forecast_points[0]["timestamp"] if forecast_points else "",
                "final_forecast_timestamp": forecast_points[-1]["timestamp"] if forecast_points else "",
                "forecast_created_at": forecast_created_at,
                "yahoo_retrieved_at": yahoo_retrieved_at,
                "interval_minutes": INTERVAL_MINUTES,
                "timezone": MARKET_TIMEZONE,
                "timezone_label": MARKET_TIMEZONE_LABEL,
                "data_source_name": data_source_name,
                "total_model_input_count": int(summary.get("input_rows", 0) or 0),
                "displayed_historical_count": len(observed_points),
                "forecast_count": len(forecast_points),
            },
        }
    )
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def build_news_research_payload(symbol: str, *, refresh: bool = False,
                                company_hint: str = "") -> dict[str, object]:
    news = dict(NEWS_SERVICE.get(symbol, refresh=refresh, company_hint=company_hint))
    for derived_key in ("research_outlook", "news_impact", "evidence_snapshot_id", "forecast_fingerprint"):
        news.pop(derived_key, None)
    news["news_pipeline"] = dict(news.get("news_pipeline") or {})
    news["news_pipeline"].pop("gold", None)
    canonical_symbol = str(news["symbol"])
    impact = assess_news(news, NEWS_SERVICE.official_name(canonical_symbol))
    news["news_impact"] = impact
    news["news_pipeline"]["impact_status"] = impact["status"]
    news["news_pipeline"]["events_processed"] = impact["events_processed"]
    NEWS_SERVICE.record_impact(impact)
    try:
        with FORECAST_LOCK:
            summary = load_summary()
            _, saved_symbol, _, source_type = source_identity(str(summary.get("input_source", "")))
            if saved_symbol == canonical_symbol and source_type == "live" and summary.get("mode") != "validation":
                fingerprint = summary_fingerprint(summary)
                news["forecast_fingerprint"] = fingerprint
                technicals = PRODUCT_PIPELINE.matching_technicals(saved_symbol, fingerprint)
                try:
                    forecast_times = pd.read_csv(FORECAST_PATH, usecols=["timestamps"])["timestamps"]
                    forecast_end = str(forecast_times.iloc[-1]) if not forecast_times.empty else None
                except (FileNotFoundError, OSError, ValueError, KeyError):
                    forecast_end = None
                outlook = research_outlook(str(summary.get("direction") or "neutral"), technicals, impact,
                                           model_as_of=(technicals or {}).get("as_of"),
                                           forecast_ends_at=forecast_end)
                news["research_outlook"] = outlook
                try:
                    news["news_pipeline"]["gold"] = save_gold(NEWS_SERVICE.cache_dir, saved_symbol, impact, outlook)
                except OSError:
                    news["news_pipeline"]["gold_warning"] = "Gold news artifact could not be saved"
                if not news["news_pipeline"].get("gold"):
                    outlook = dict(outlook)
                    outlook["why"] += " The Gold news artifact is unavailable; review this view as degraded."
                    outlook["warning"] = "News evidence artifact unavailable; this view is degraded."
                    news["research_outlook"] = outlook
                try:
                    manifest = json.loads(PRODUCT_PIPELINE._latest.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    manifest = None
                try:
                    content = create_content(
                        symbol=saved_symbol, exchange="NSE" if saved_symbol.endswith(".NS") else "BSE",
                        summary=summary, fingerprint=fingerprint,
                        forecast_sha256=hashlib.sha256(FORECAST_PATH.read_bytes()).hexdigest(),
                        input_sha256=hashlib.sha256(UPLOADED_DATA_PATH.read_bytes()).hexdigest(),
                        market=manifest, technicals=technicals, news=news, impact=impact, outlook=outlook,
                        news_gold=news["news_pipeline"].get("gold"),
                        technical_version=(technicals or {}).get("analysis_version"),
                    )
                    news["evidence_snapshot_id"] = save_snapshot(EVIDENCE_DIR, content)["snapshot_id"]
                except (OSError, ValueError, TypeError):
                    news.pop("research_outlook", None)
                    news["evidence_snapshot_warning"] = "A joined evidence snapshot is unavailable."
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        pass
    return news


def run_forecast(
    csv_text: str,
    input_label: str = "uploaded_market_data.csv",
    request_id: int | str | None = None,
    forecast_bars: int | str | None = None,
    inference_settings: dict[str, object] | None = None,
) -> dict[str, object]:
    """Save a selected CSV locally and run the existing Kronos forecast script."""
    if not csv_text.strip():
        raise ValueError("Select a CSV file before starting a forecast.")
    if len(csv_text.encode("utf-8")) > 5_000_000:
        raise ValueError("Use a CSV smaller than 5 MB for this local demo.")

    market_data = validate_market_csv(csv_text)
    forecast_bars = resolve_forecast_bars(forecast_bars)
    settings = inference_settings or {}
    cache_key = forecast_cache_key(
        market_data,
        mode="forecast",
        input_label=input_label,
        forecast_bars=forecast_bars,
        temperature=float(settings.get("temperature", DEFAULT_TEMPERATURE) or DEFAULT_TEMPERATURE),
        top_k=int(settings.get("top_k", DEFAULT_TOP_K) or DEFAULT_TOP_K),
        top_p=float(settings.get("top_p", DEFAULT_TOP_P) or DEFAULT_TOP_P),
        sample_count=int(settings.get("sample_count", DEFAULT_SAMPLE_COUNT) or DEFAULT_SAMPLE_COUNT),
    )
    with FORECAST_LOCK:
        cached_summary = restore_forecast_cache(cache_key)
        if cached_summary:
            return build_dashboard_payload(cached_summary, market_data, request_id)
        UPLOADED_DATA_PATH.write_text(csv_text, encoding="utf-8")
        yahoo_retrieved_at = None
        if input_label.lower().endswith("live 5-minute data"):
            yahoo_retrieved_at = pd.Timestamp.now(tz=MARKET_TIMEZONE).isoformat()
        summary = run_kronos_forecast(
            input_path=UPLOADED_DATA_PATH,
            input_label=input_label,
            forecast_bars=forecast_bars,
            temperature=settings.get("temperature"),
            top_k=settings.get("top_k"),
            top_p=settings.get("top_p"),
            sample_count=settings.get("sample_count"),
            yahoo_retrieved_at=yahoo_retrieved_at,
        )
        summary["cache_hit"] = False
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        save_forecast_cache(cache_key)
        return build_dashboard_payload(summary, market_data, request_id)


def fetch_live_forecast(
    ticker: str,
    exchange: str = "NSE",
    request_id: int | str | None = None,
    forecast_bars: int | str | None = None,
) -> dict[str, object]:
    """Fetch Indian-market OHLCV data and pass it through the local forecast flow."""
    source_ticker, clean_data, capture_id = _fetch_product_market_data_with_capture(ticker, exchange)
    payload = run_forecast(
        clean_data.to_csv(index=False),
        f"{source_ticker} live 5-minute data",
        request_id,
        forecast_bars,
    )
    _complete_product_pipeline(capture_id, clean_data.tail(LOOKBACK_BARS), payload)
    return payload


def _fetch_product_market_data_with_capture(ticker: str, exchange: str) -> tuple[str, pd.DataFrame, str | None]:
    result = LIVE_MARKET_DATA_SERVICE.get_bars(MarketDataRequest(ticker, exchange))
    source_ticker = str(result.provenance["source_symbol"])
    clean_data = result.bars.rename(columns={"timestamp": "timestamps"})[REQUIRED_COLUMNS].dropna()
    try:
        capture_id = PRODUCT_PIPELINE.capture(result)
    except Exception:
        capture_id = None
    return source_ticker, clean_data, capture_id


def _complete_product_pipeline(capture_id: str | None, context: pd.DataFrame,
                               payload: dict[str, object], *, validation: bool = False) -> None:
    if capture_id is None:
        return
    try:
        PRODUCT_PIPELINE.complete(capture_id, context, payload, validation=validation)
    except Exception:
        try:
            PRODUCT_PIPELINE.record_error("Gold artifact could not be built from the saved forecast.")
        except Exception:
            pass


def fetch_product_market_data(ticker: str, exchange: str = "NSE") -> tuple[str, pd.DataFrame]:
    source_ticker, clean_data, _ = _fetch_product_market_data_with_capture(ticker, exchange)
    return source_ticker, clean_data


def fetch_live_market_data(ticker: str, exchange: str = "NSE") -> tuple[str, pd.DataFrame]:
    """Compatibility entry point for live callers; market bars use the service."""
    return fetch_product_market_data(ticker, exchange)


def fetch_live_validation(
    ticker: str,
    exchange: str = "NSE",
    request_id: int | str | None = None,
    forecast_bars: int | str | None = None,
) -> dict[str, object]:
    source_ticker, clean_data, capture_id = _fetch_product_market_data_with_capture(ticker, exchange)
    payload = run_validation(
        clean_data.to_csv(index=False),
        f"{source_ticker} live 5-minute data",
        request_id,
        forecast_bars,
    )
    horizon = int(payload.get("forecast_rows") or resolve_forecast_bars(forecast_bars))
    context = clean_data.iloc[-(LOOKBACK_BARS + horizon):-horizon]
    _complete_product_pipeline(capture_id, context, payload, validation=True)
    return payload


class DashboardHandler(SimpleHTTPRequestHandler):
    PROTECTED_GET = frozenset({"/api/news", "/api/search", "/api/symbol-search", "/api/evidence-snapshot", "/api/agents/result"})
    BROWSER_FETCH_GET = frozenset({"/api/news", "/api/search", "/api/symbol-search", "/api/agents/result"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT / "app"), **kwargs)

    def translate_path(self, path: str) -> str:
        route = urlparse(path).path
        if route not in PUBLIC_ASSETS:
            return str(PROJECT_ROOT / "app" / "__not_public__")
        return str(PROJECT_ROOT / "app" / route.removeprefix("/app/"))

    def log_message(self, format: str, *args: object) -> None:
        # Request lines can carry attacker-supplied tokens; never log query strings or bodies.
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _address(self) -> str:
        return str(self.client_address[0])

    def _authorized(self) -> bool:
        return ACCESS_GUARD.authenticated(self._address(), self.headers.get("Cookie", ""))

    def _require_access(self, route: str, *, expensive: bool = False) -> bool:
        if not self._authorized():
            self.send_json({"error": "Unlock this laptop's dashboard to continue.", "code": "AUTH_REQUIRED"}, HTTPStatus.UNAUTHORIZED)
            return False
        if expensive and not ACCESS_GUARD.allow(self._address(), route, 8, 600, daily=48):
            self.send_json({"error": "Local request limit reached. Please try later.", "code": "RATE_LIMITED"}, HTTPStatus.TOO_MANY_REQUESTS)
            return False
        return True

    def _public_asset(self, head: bool = False) -> None:
        # Exact URL allowlist; no percent-decoding or filesystem path supplied by the caller.
        if not valid_host(self.headers.get("Host", "")) or urlparse(self.path).path not in PUBLIC_ASSETS:
            self.send_error(HTTPStatus.NOT_FOUND, "Public asset not found")
            return
        if head:
            super().do_HEAD()
        else:
            super().do_GET()

    def do_HEAD(self) -> None:
        self._public_asset(head=True)

    def _method_not_allowed(self) -> None:
        self.send_json({"error": "Method not allowed."}, HTTPStatus.METHOD_NOT_ALLOWED,
                       extra_headers={"Allow": "GET, HEAD, POST"})

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK,
                  extra_headers: dict[str, str] | None = None) -> None:
        if int(status) >= 400:
            ACCESS_GUARD.record_failure(self._address(), urlparse(self.path).path)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self) -> None:
        if not valid_host(self.headers.get("Host", "")):
            self.send_error(HTTPStatus.NOT_FOUND, "Public asset not found")
            return
        parsed_path = urlparse(self.path)
        if parsed_path.path in self.PROTECTED_GET and not same_origin(self.headers):
            self.send_json({"error": "Cross-origin request rejected."}, HTTPStatus.FORBIDDEN)
            return
        if parsed_path.path in self.BROWSER_FETCH_GET and self.headers.get("X-Kronos-Request") != "dashboard":
            self.send_json({"error": "Dashboard request required."}, HTTPStatus.FORBIDDEN)
            return
        if parsed_path.path in LOCAL_READ and not is_loopback(self._address()):
            self.send_json({"error": "Local research access only."}, HTTPStatus.FORBIDDEN)
            return
        if parsed_path.path == "/api/news":
            if not self._require_access("/api/news", expensive=True):
                return
            params = parse_qs(parsed_path.query)
            try:
                self.send_json(build_news_research_payload(
                    params.get("symbol", [""])[0],
                    refresh=params.get("refresh", ["0"])[0] == "1",
                    company_hint=params.get("name", [""])[0],
                ))
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed_path.path == "/api/pipeline":
            try:
                pipeline = PRODUCT_PIPELINE.snapshot()
                pipeline["stages"]["news"] = NEWS_SERVICE.pipeline_stage()
                load_local_key()
                pipeline["stages"]["agents"] = AGENT_TEAM.health()
                intelligence = pipeline["stages"].get("intelligence") or {}
                intelligence["warnings"] = [warning for warning in intelligence.get("warnings", [])
                                            if warning != "Agents are not connected"]
                self.send_json(pipeline)
            except (OSError, ValueError, json.JSONDecodeError):
                self.send_json({"error": "Local pipeline status is unavailable."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed_path.path == "/api/dashboard":
            try:
                self.send_json(build_dashboard_payload(load_summary()))
            except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed_path.path in {"/api/symbol-search", "/api/search"}:
            if not self._require_access("/api/search"):
                return
            params = parse_qs(parsed_path.query)
            self.send_json(
                {
                    "query": params.get("q", [""])[0],
                    "results": symbol_search(
                        params.get("q", [""])[0],
                        params.get("exchange", ["NSE"])[0],
                    ),
                    "stats": index_stats() if parsed_path.path == "/api/search" else None,
                }
            )
            return
        if parsed_path.path == "/api/research/status":
            from research.registry import ExperimentRegistry

            params = parse_qs(parsed_path.query)
            registry = ExperimentRegistry()
            try:
                self.send_json(registry.summary(params.get("run_id", [None])[0]))
            finally:
                registry.close()
            return
        if parsed_path.path == "/api/research/report":
            from research.config import REPORTS_DIR

            params = parse_qs(parsed_path.query)
            run_id = Path(params.get("run_id", [""])[0]).name
            report_path = REPORTS_DIR / f"{run_id}.md"
            if not run_id or not report_path.exists():
                self.send_json({"error": "Research report was not found for that run ID."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"run_id": run_id, "markdown": report_path.read_text(encoding="utf-8")})
            return
        if parsed_path.path == "/api/research/runs":
            from research.registry import ExperimentRegistry

            params = parse_qs(parsed_path.query)
            limit = min(100, max(1, int(params.get("limit", ["20"])[0] or 20)))
            registry = ExperimentRegistry()
            try:
                rows = registry.connection.execute(
                    "select run_id,status,started_at,finished_at from runs order by started_at desc limit ?",
                    (limit,),
                ).fetchall()
                self.send_json({"runs": [dict(row) for row in rows]})
            finally:
                registry.close()
            return
        if parsed_path.path == "/api/research/experiments":
            from research.registry import ExperimentRegistry

            params = parse_qs(parsed_path.query)
            run_id = Path(params.get("run_id", [""])[0]).name
            limit = min(100, max(1, int(params.get("limit", ["50"])[0] or 50)))
            offset = max(0, int(params.get("offset", ["0"])[0] or 0))
            registry = ExperimentRegistry()
            try:
                rows = registry.connection.execute(
                    """
                    select e.experiment_id,e.run_id,e.model_name,e.horizon_bars,e.symbol,e.status,e.started_at,e.finished_at,
                           m.mae,m.normalized_mae,m.rmse,m.mase,m.directional_match
                    from experiments e left join metrics m on e.experiment_id=m.experiment_id
                    where (?='' or e.run_id=?)
                    order by e.started_at desc limit ? offset ?
                    """,
                    (run_id, run_id, limit, offset),
                ).fetchall()
                self.send_json({"experiments": [dict(row) for row in rows], "limit": limit, "offset": offset})
            finally:
                registry.close()
            return
        if parsed_path.path == "/api/research/experiment":
            from research.registry import ExperimentRegistry

            params = parse_qs(parsed_path.query)
            experiment_id = params.get("experiment_id", [""])[0]
            registry = ExperimentRegistry()
            try:
                spec = registry.connection.execute("select * from experiment_specs where experiment_id=?", (experiment_id,)).fetchone()
                artifacts = registry.connection.execute("select * from artifacts where experiment_id=? order by artifact_type", (experiment_id,)).fetchall()
                if not spec:
                    self.send_json({"error": "Experiment was not found."}, HTTPStatus.NOT_FOUND)
                else:
                    self.send_json({"spec": dict(spec), "artifacts": [dict(row) for row in artifacts]})
            finally:
                registry.close()
            return
        if parsed_path.path == "/api/research/failures":
            from research.registry import ExperimentRegistry

            params = parse_qs(parsed_path.query)
            run_id = Path(params.get("run_id", [""])[0]).name
            registry = ExperimentRegistry()
            try:
                rows = registry.connection.execute(
                    """
                    select e.experiment_id,e.run_id,e.model_name,e.symbol,e.horizon_bars,m.normalized_mae,m.mae,e.error
                    from experiments e left join metrics m on e.experiment_id=m.experiment_id
                    where (?='' or e.run_id=?)
                    order by coalesce(m.normalized_mae, m.mae, 0) desc limit 20
                    """,
                    (run_id, run_id),
                ).fetchall()
                self.send_json({"failures": [dict(row) for row in rows]})
            finally:
                registry.close()
            return
        if parsed_path.path == "/api/explanation":
            try:
                summary = load_summary()
                cached = load_cached_explanation(summary)
                self.send_json(
                    {
                        "available": bool(cached),
                        "explanation": (
                            format_explanation_currency(cached.get("explanation", ""), summary)
                            if cached
                            else None
                        ),
                        "summary_fingerprint": summary_fingerprint(summary),
                    }
                )
            except (FileNotFoundError, json.JSONDecodeError) as error:
                self.send_json({"available": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed_path.path == "/api/evidence-snapshot":
            if not self._require_access("/api/evidence-snapshot"):
                return
            digest = parse_qs(parsed_path.query).get("id", [""])[0]
            record = read_snapshot(EVIDENCE_DIR, digest)
            self.send_json(record if record else {"error": "Evidence snapshot not found."},
                           HTTPStatus.OK if record else HTTPStatus.NOT_FOUND)
            return
        if parsed_path.path == "/api/agents/result":
            if not self._require_access("/api/agents/result"):
                return
            digest = parse_qs(parsed_path.query).get("id", [""])[0]
            try:
                load_local_key()
                self.send_json(AGENT_TEAM.result(current_agent_snapshot(digest)))
            except AgentError as error:
                self.send_json({"error": str(error), "code": error.code}, HTTPStatus.CONFLICT if error.code == "STALE_SNAPSHOT" else HTTPStatus.NOT_FOUND)
            return
        self._public_asset()

    def do_POST(self) -> None:
        if not valid_host(self.headers.get("Host", "")):
            self.send_json({"error": "Invalid local host."}, HTTPStatus.FORBIDDEN)
            return
        if not same_origin(self.headers):
            self.send_json({"error": "Cross-origin request rejected."}, HTTPStatus.FORBIDDEN)
            return
        if self.path == "/api/session":
            if not ACCESS_GUARD.allow(self._address(), "/api/session", 5, 300):
                self.send_json({"error": "Too many unlock attempts."}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            if not local_secret("KRONOS_LAN_ACCESS_CODE", ENV_PATH):
                self.send_json({"error": "LAN access code is not configured on the laptop.",
                                "code": "LAN_CODE_UNCONFIGURED"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1024 or "application/json" not in self.headers.get("Content-Type", ""):
                    raise ValueError()
                code = json.loads(self.rfile.read(length))["access_code"]
                if not isinstance(code, str):
                    raise ValueError()
            except (ValueError, KeyError, json.JSONDecodeError, TypeError):
                self.send_json({"error": "Invalid unlock request."}, HTTPStatus.BAD_REQUEST)
                return
            token = ACCESS_GUARD.login(self._address(), code)
            if not token:
                self.send_json({"error": "Access code was not accepted."}, HTTPStatus.UNAUTHORIZED)
                return
            self.send_json({"authenticated": True}, extra_headers={
                "Set-Cookie": f"kronos_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"})
            return
        if self.path in EXPENSIVE_POST:
            if not self._require_access(self.path, expensive=True):
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                self.send_json({"error": "JSON request required."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > 6_000_000:
                self.send_json({"error": "Request is too large."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
        if self.path == "/api/forecast":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                filename = Path(str(request_data.get("filename", "uploaded_market_data.csv"))).name
                self.send_json(
                    run_forecast(
                        request_data.get("csv", ""),
                        filename,
                        request_data.get("request_id"),
                        request_data.get("forecast_bars") or request_data.get("horizon"),
                    )
                )
            except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/validation":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                filename = Path(str(request_data.get("filename", "uploaded_market_data.csv"))).name
                self.send_json(
                    run_validation(
                        request_data.get("csv", ""),
                        filename,
                        request_data.get("request_id"),
                        request_data.get("forecast_bars") or request_data.get("horizon"),
                    )
                )
            except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/live-forecast":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                self.send_json(
                    fetch_live_forecast(
                        request_data.get("ticker", ""),
                        request_data.get("exchange", "NSE"),
                        request_data.get("request_id"),
                        request_data.get("forecast_bars") or request_data.get("horizon"),
                    )
                )
            except MarketDataError as error:
                self.send_json({"error": str(error), "code": error.code}, HTTPStatus.BAD_REQUEST)
            except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/live-validation":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                self.send_json(
                    fetch_live_validation(
                        request_data.get("ticker", ""),
                        request_data.get("exchange", "NSE"),
                        request_data.get("request_id"),
                        request_data.get("forecast_bars") or request_data.get("horizon"),
                    )
                )
            except MarketDataError as error:
                self.send_json({"error": str(error), "code": error.code}, HTTPStatus.BAD_REQUEST)
            except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/explanation":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request_data = (
                    json.loads(self.rfile.read(content_length).decode("utf-8"))
                    if content_length
                    else {}
                )
                self.send_json(generate_explanation(request_data.get("summary_fingerprint")))
            except Exception:
                self.send_json(
                    {"error": "The explanation could not be generated. Check your key and API billing, then try again."},
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if self.path == "/api/agents/run":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= content_length <= 256:
                    raise ValueError("Invalid agent request size")
                request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(request_data, dict) or set(request_data) != {"snapshot_id"} or \
                        not isinstance(request_data["snapshot_id"], str):
                    raise ValueError("A snapshot ID is required")
                record = current_agent_snapshot(request_data["snapshot_id"])
                load_local_key()
                self.send_json(AGENT_TEAM.run(record))
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid AI research request."}, HTTPStatus.BAD_REQUEST)
            except AgentError as error:
                status = (HTTPStatus.SERVICE_UNAVAILABLE if error.code in {"UNAVAILABLE", "LEDGER_UNAVAILABLE"} else
                          HTTPStatus.TOO_MANY_REQUESTS if error.code == "COST_LIMIT" else
                          HTTPStatus.CONFLICT if error.code == "STALE_SNAPSHOT" else HTTPStatus.BAD_REQUEST)
                self.send_json({"error": str(error), "code": error.code}, status)
            except Exception:
                self.send_json({"error": "AI Research Team could not complete the request.", "code": "AGENT_ERROR"},
                               HTTPStatus.BAD_GATEWAY)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), DashboardHandler)
    print("Kronos Copilot dashboard: http://127.0.0.1:8000/app/dashboard.html")
    print("LAN access: use http://<this-laptop-ip>:8000/app/dashboard.html on the same Wi-Fi")
    server.serve_forever()
