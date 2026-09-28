"""Deterministic, historical-only technical signals for research windows."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


MIN_BARS = 60


def _signal(value: float, center: float, scale: float, bullish_above: bool = True) -> tuple[str, float]:
    distance = (value - center) / max(abs(scale), 1e-12)
    if not bullish_above:
        distance = -distance
    if abs(distance) < 0.05:
        return "neutral", 0.0
    return ("bullish" if distance > 0 else "bearish"), round(min(1.0, abs(distance)), 4)


def analyze(context: pd.DataFrame) -> dict[str, Any]:
    """Analyze only bars at or before a forecast cutoff; no future inputs."""
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(context.columns) or len(context) < MIN_BARS:
        raise ValueError("At least 60 historical OHLCV bars are required.")
    frame = context.copy()
    times = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if times.isna().any() or not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Historical timestamps must be ordered and unique.")
    for column in required - {"timestamp"}:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].map(math.isfinite).all():
            raise ValueError(f"Non-finite {column} in historical bars.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame["volume"] < 0).any():
        raise ValueError("Invalid historical price or volume.")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
            (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid historical OHLC ordering.")

    close, high, low, volume = (frame[key] for key in ("close", "high", "low", "volume"))
    last = float(close.iloc[-1])
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    if float(loss.iloc[-1]) == 0:
        rsi = 100.0 if float(gain.iloc[-1]) > 0 else 50.0
    else:
        rsi = 100.0 - 100.0 / (1.0 + float(gain.iloc[-1] / loss.iloc[-1]))
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    bb_std = close.rolling(20).std(ddof=0)
    bb_upper = float(sma20.iloc[-1] + 2 * bb_std.iloc[-1])
    bb_lower = float(sma20.iloc[-1] - 2 * bb_std.iloc[-1])
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    roc = float((last / float(close.iloc[-11]) - 1) * 100)
    volume_sma = float(volume.rolling(20).mean().iloc[-1])
    spike = float(volume.iloc[-1] / volume_sma) if volume_sma > 0 else 0.0
    price_scale = max(atr, last * 0.001)
    specs = [
        ("EMA20", float(ema20.iloc[-1]), *_signal(last, float(ema20.iloc[-1]), price_scale), "Close relative to the 20-bar exponential mean."),
        ("EMA50", float(ema50.iloc[-1]), *_signal(last, float(ema50.iloc[-1]), price_scale), "Close relative to the 50-bar exponential mean."),
        ("SMA20", float(sma20.iloc[-1]), *_signal(last, float(sma20.iloc[-1]), price_scale), "Close relative to the 20-bar simple mean."),
        ("SMA50", float(sma50.iloc[-1]), *_signal(last, float(sma50.iloc[-1]), price_scale), "Close relative to the 50-bar simple mean."),
        ("RSI14", rsi, *_signal(rsi, 50, 25), "Wilder-style 14-bar gain/loss momentum relative to 50."),
        ("MACD", float(macd.iloc[-1]), *_signal(float(macd.iloc[-1]), float(macd_signal.iloc[-1]), price_scale), "12/26 EMA difference relative to its 9-bar signal."),
        ("MACD signal", float(macd_signal.iloc[-1]), *_signal(float(macd_signal.iloc[-1]), 0, price_scale), "Nine-bar exponential mean of MACD relative to zero."),
        ("Bollinger Bands", {"lower": bb_lower, "middle": float(sma20.iloc[-1]), "upper": bb_upper}, *_signal(last, float(sma20.iloc[-1]), max(bb_upper - bb_lower, price_scale)), "Close position within 20-bar, two-standard-deviation bands."),
        ("ATR14", atr, "high" if atr / last >= 0.015 else "normal", round(min(1.0, atr / last / 0.03), 4), "Wilder-smoothed true range; volatility, not direction."),
        ("ROC10", roc, *_signal(roc, 0, 2), "Ten-bar percentage rate of change."),
        ("Volume SMA20", volume_sma, "normal", 0.0, "Mean volume across the latest 20 bars; no directional claim."),
        ("Volume spike", spike, "high" if spike >= 1.8 else "normal", round(min(1.0, max(0.0, spike - 1) / 2), 4), "Latest volume divided by its 20-bar mean."),
    ]
    indicators = [{"indicator": name, "value": value, "signal": signal, "strength": strength, "reason": reason}
                  for name, value, signal, strength, reason in specs]
    trend = "bullish" if last > float(ema50.iloc[-1]) and ema20.iloc[-1] > ema50.iloc[-1] else (
        "bearish" if last < float(ema50.iloc[-1]) and ema20.iloc[-1] < ema50.iloc[-1] else "mixed")
    momentum = "bullish" if rsi > 55 and roc > 0 and macd.iloc[-1] > macd_signal.iloc[-1] else (
        "bearish" if rsi < 45 and roc < 0 and macd.iloc[-1] < macd_signal.iloc[-1] else "mixed")
    atr_pct = atr / last * 100
    regime = "HIGH_VOLATILITY" if atr_pct >= 1.5 else (
        "LOW_VOLATILITY" if atr_pct <= 0.3 else (
            "TRENDING_BULL" if trend == "bullish" and momentum == "bullish" else (
                "TRENDING_BEAR" if trend == "bearish" and momentum == "bearish" else "SIDEWAYS")))
    return {"as_of": str(frame["timestamp"].iloc[-1]), "indicators": indicators,
            "trend": trend, "momentum": momentum, "volatility": "high" if atr_pct >= 1.5 else ("low" if atr_pct <= 0.3 else "normal"),
            "volume_condition": "spike" if spike >= 1.8 else "normal", "regime": regime,
            "atr_pct": round(atr_pct, 6)}
