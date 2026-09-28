"""Simple deterministic close-price baselines."""

from __future__ import annotations

import pandas as pd


def persistence(context: pd.DataFrame, future_timestamps: pd.Series) -> pd.DataFrame:
    last_close = float(context["close"].iloc[-1])
    return pd.DataFrame({"timestamp": future_timestamps.reset_index(drop=True), "close": [last_close] * len(future_timestamps)})


def simple_drift(context: pd.DataFrame, future_timestamps: pd.Series, lookback: int = 20) -> pd.DataFrame:
    closes = context["close"].astype(float).tail(max(2, lookback))
    step = float(closes.diff().dropna().mean())
    last_close = float(context["close"].iloc[-1])
    values = [last_close + step * (index + 1) for index in range(len(future_timestamps))]
    return pd.DataFrame({"timestamp": future_timestamps.reset_index(drop=True), "close": values})


def simple_momentum(context: pd.DataFrame, future_timestamps: pd.Series, short: int = 10, long: int = 50) -> pd.DataFrame:
    closes = context["close"].astype(float)
    short_mean = float(closes.tail(short).mean())
    long_mean = float(closes.tail(long).mean())
    step = (short_mean - long_mean) / max(long, 1)
    last_close = float(closes.iloc[-1])
    values = [last_close + step * (index + 1) for index in range(len(future_timestamps))]
    return pd.DataFrame({"timestamp": future_timestamps.reset_index(drop=True), "close": values})


BASELINES = {
    "persistence": persistence,
    "drift": simple_drift,
    "momentum": simple_momentum,
}
