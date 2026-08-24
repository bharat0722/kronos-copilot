"""Shared forecast timing settings for Kronos Copilot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


LOOKBACK_BARS = 400
FORECAST_HORIZONS = {
    "2h": 24,
    "session": 75,
    "extended": 120,
}
DEFAULT_FORECAST_HORIZON = "session"
FORECAST_BARS = FORECAST_HORIZONS[DEFAULT_FORECAST_HORIZON]
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_K = 0
DEFAULT_TOP_P = 0.9
DEFAULT_SAMPLE_COUNT = 1
EXPERIMENTAL_TEMPERATURE = 1.2
EXPERIMENTAL_TOP_P = 0.95
EXPERIMENTAL_SAMPLE_COUNT = 3
INTERVAL_MINUTES = 5
MARKET_TIMEZONE = "Asia/Kolkata"
MARKET_TIMEZONE_LABEL = "IST"
SESSION_START = time(9, 15)
SESSION_END = time(15, 30)


def market_zone() -> ZoneInfo:
    return ZoneInfo(MARKET_TIMEZONE)


def coerce_market_timestamps(values: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values, errors="coerce")
    if timestamps.dt.tz is None:
        return timestamps.dt.tz_localize(market_zone())
    return timestamps.dt.tz_convert(market_zone())


def ensure_market_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(market_zone())
    return timestamp.tz_convert(market_zone())


def _session_timestamp(day: object, clock: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day, clock), tz=market_zone())


def _next_weekday(day: object) -> object:
    next_day = day + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day


def next_valid_market_bar(candidate: pd.Timestamp) -> pd.Timestamp:
    candidate = ensure_market_timestamp(candidate)
    interval = pd.Timedelta(minutes=INTERVAL_MINUTES)

    while True:
        day = candidate.date()
        if candidate.weekday() >= 5:
            return _session_timestamp(_next_weekday(day), SESSION_START)

        session_start = _session_timestamp(day, SESSION_START)
        last_bar_start = _session_timestamp(day, SESSION_END) - interval

        if candidate < session_start:
            return session_start
        if candidate <= last_bar_start:
            offset_minutes = int((candidate - session_start).total_seconds() // 60)
            remainder = offset_minutes % INTERVAL_MINUTES
            if remainder:
                candidate += pd.Timedelta(minutes=INTERVAL_MINUTES - remainder)
            return candidate if candidate <= last_bar_start else _session_timestamp(_next_weekday(day), SESSION_START)

        candidate = _session_timestamp(_next_weekday(day), SESSION_START)


def build_forecast_timestamps(last_observed: object, count: int = FORECAST_BARS) -> pd.Series:
    interval = pd.Timedelta(minutes=INTERVAL_MINUTES)
    candidate = ensure_market_timestamp(last_observed) + interval
    timestamps = []
    while len(timestamps) < count:
        candidate = next_valid_market_bar(candidate)
        timestamps.append(candidate)
        candidate += interval
    return pd.Series(timestamps)


def resolve_forecast_bars(value: object = None) -> int:
    if value is None or value == "":
        return FORECAST_BARS
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in FORECAST_HORIZONS:
            return FORECAST_HORIZONS[normalized]
        if normalized.endswith(" bars"):
            normalized = normalized[:-5].strip()
        value = normalized
    try:
        bars = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a supported forecast horizon: 24, 75, or 120 bars.") from error
    if bars not in set(FORECAST_HORIZONS.values()):
        raise ValueError("Choose a supported forecast horizon: 24, 75, or 120 bars.")
    return bars


def horizon_label(count: int = FORECAST_BARS) -> str:
    if count == FORECAST_HORIZONS["2h"]:
        return "2 hours"
    if count == FORECAST_HORIZONS["session"]:
        return "Next 75 market bars"
    if count == FORECAST_HORIZONS["extended"]:
        return "Extended 120 market bars"
    return f"Next {count} market bars"


def horizon_detail(count: int = FORECAST_BARS) -> str:
    if count == FORECAST_HORIZONS["session"]:
        return "Equivalent to one full trading session · 6h 15m of trading · Closed-market hours skipped"
    return f"{count} predicted five-minute market bars · {trading_duration_label(count)} of trading"


def trading_duration_label(count: int = FORECAST_BARS) -> str:
    total_minutes = count * INTERVAL_MINUTES
    hours, minutes = divmod(total_minutes, 60)
    hour_label = "hour" if hours == 1 else "hours"
    if not minutes:
        return f"{hours} {hour_label}"
    minute_label = "minute" if minutes == 1 else "minutes"
    return f"{hours} {hour_label} {minutes} {minute_label}"
