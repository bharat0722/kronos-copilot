"""Pre-cutoff regime tags derived only from context bars."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


def tag_regime(context: pd.DataFrame) -> dict[str, object]:
    closes = pd.to_numeric(context["close"], errors="coerce").dropna()
    returns = closes.pct_change().dropna()
    if len(closes) < 30 or returns.empty:
        return {
            "trend": "unknown",
            "volatility": "unknown",
            "open_close_zone": "unknown",
            "momentum": "unknown",
            "relative_volume": "unknown",
            "cross_session": False,
            "gap_state": "unknown",
            "future_broad_market_regime": None,
            "future_sector_regime": None,
            "future_volatility_index_state": None,
            "future_macro_state": None,
        }
    recent = closes.tail(30)
    move_pct = (float(recent.iloc[-1]) - float(recent.iloc[0])) / float(recent.iloc[0]) * 100
    if move_pct > 1.0:
        trend = "uptrend"
    elif move_pct < -1.0:
        trend = "downtrend"
    else:
        trend = "flat"
    volatility_value = float(returns.tail(75).std(ddof=0) * 100)
    volatility = "high_volatility" if volatility_value >= 0.6 else "low_volatility" if volatility_value <= 0.2 else "normal_volatility"
    last_ts = pd.Timestamp(context["timestamp"].iloc[-1]).tz_convert("Asia/Kolkata")
    minutes = last_ts.hour * 60 + last_ts.minute
    if minutes <= 10 * 60:
        zone = "near_open"
    elif minutes >= 14 * 60 + 45:
        zone = "near_close"
    else:
        zone = "mid_session"
    momentum_move = float(closes.tail(10).iloc[-1] - closes.tail(10).iloc[0]) / float(closes.tail(10).iloc[0]) * 100
    momentum = "positive" if momentum_move > 0.15 else "negative" if momentum_move < -0.15 else "neutral"
    relative_volume = "unknown"
    if "volume" in context.columns and len(context) >= 75:
        volumes = pd.to_numeric(context["volume"], errors="coerce").dropna()
        if len(volumes) >= 75 and float(volumes.tail(20).mean()) > 0:
            ratio = float(volumes.tail(20).mean() / volumes.tail(75).mean())
            relative_volume = "elevated" if ratio >= 1.25 else "low" if ratio <= 0.75 else "normal"
    timestamps = pd.to_datetime(context["timestamp"]).dt.tz_convert("Asia/Kolkata")
    gaps = timestamps.diff().dropna()
    cross_session = timestamps.dt.date.nunique() > 1
    gap_state = "has_session_gap" if (gaps > timedelta(minutes=5)).any() else "continuous_session"
    return {
        "trend": trend,
        "trend_30_bar_pct": move_pct,
        "volatility": volatility,
        "volatility_pct": volatility_value,
        "open_close_zone": zone,
        "momentum": momentum,
        "momentum_10_bar_pct": momentum_move,
        "relative_volume": relative_volume,
        "cross_session": bool(cross_session),
        "gap_state": gap_state,
        "future_broad_market_regime": None,
        "future_sector_regime": None,
        "future_volatility_index_state": None,
        "future_macro_state": None,
    }
