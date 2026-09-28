"""Temporally safe walk-forward windows."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BenchmarkWindow:
    window_id: str
    symbol: str
    horizon_bars: int
    lookback_bars: int
    stride_bars: int
    session_policy: str
    context_start_index: int
    context_end_index: int
    future_start_index: int
    future_end_index: int
    context_start: str
    context_end: str
    cutoff_timestamp: str
    future_start: str
    future_end: str
    overlap_bars: int = 0
    overlap_ratio: float = 0.0


def _same_session(timestamps: pd.Series) -> bool:
    dates = pd.to_datetime(timestamps).dt.tz_convert("Asia/Kolkata").dt.date
    return dates.nunique() == 1


def generate_windows(
    bars: pd.DataFrame,
    *,
    symbol: str,
    lookback_bars: int,
    horizon_bars: int,
    stride_bars: int,
    session_policy: str = "cross_session_allowed",
    max_windows: int = 0,
) -> list[BenchmarkWindow]:
    if stride_bars < 1:
        raise ValueError("stride_bars must be at least 1")
    if session_policy not in {"cross_session_allowed", "same_session_only"}:
        raise ValueError("session_policy must be cross_session_allowed or same_session_only")
    if len(bars) < lookback_bars + horizon_bars:
        return []
    timestamps = pd.to_datetime(bars["timestamp"], errors="raise")
    windows: list[BenchmarkWindow] = []
    start = 0
    while start + lookback_bars + horizon_bars <= len(bars):
        context_start = start
        context_end = start + lookback_bars - 1
        future_start = context_end + 1
        future_end = future_start + horizon_bars - 1
        future_times = timestamps.iloc[future_start:future_end + 1]
        if session_policy == "same_session_only" and not _same_session(future_times):
            start += stride_bars
            continue
        overlap_bars = max(0, horizon_bars - stride_bars)
        window = BenchmarkWindow(
            window_id=f"{symbol}_{horizon_bars}_{context_start}_{future_end}",
            symbol=symbol,
            horizon_bars=horizon_bars,
            lookback_bars=lookback_bars,
            stride_bars=stride_bars,
            session_policy=session_policy,
            context_start_index=context_start,
            context_end_index=context_end,
            future_start_index=future_start,
            future_end_index=future_end,
            context_start=timestamps.iloc[context_start].isoformat(),
            context_end=timestamps.iloc[context_end].isoformat(),
            cutoff_timestamp=timestamps.iloc[context_end].isoformat(),
            future_start=timestamps.iloc[future_start].isoformat(),
            future_end=timestamps.iloc[future_end].isoformat(),
            overlap_bars=overlap_bars,
            overlap_ratio=overlap_bars / horizon_bars if horizon_bars else 0.0,
        )
        windows.append(window)
        if max_windows and len(windows) >= max_windows:
            break
        start += stride_bars
    return windows


def split_window(bars: pd.DataFrame, window: BenchmarkWindow) -> tuple[pd.DataFrame, pd.DataFrame]:
    context = bars.iloc[window.context_start_index:window.context_end_index + 1].reset_index(drop=True)
    future = bars.iloc[window.future_start_index:window.future_end_index + 1].reset_index(drop=True)
    if context["timestamp"].max() >= future["timestamp"].min():
        raise AssertionError("Temporal leakage detected: context reaches hidden future.")
    return context, future


def validate_window_bounds(bars: pd.DataFrame, window: BenchmarkWindow) -> None:
    if window.context_end_index >= window.future_start_index:
        raise AssertionError("Temporal leakage detected: context index reaches hidden future.")
    context, future = split_window(bars, window)
    if len(context) != window.lookback_bars:
        raise AssertionError("Context length does not match lookback.")
    if len(future) != window.horizon_bars:
        raise AssertionError("Future length does not match horizon.")
