"""Adapter around the existing Kronos forecast implementation."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KRONOS_ROOT = PROJECT_ROOT / "vendor" / "Kronos-master"
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(KRONOS_ROOT))

from first_forecast import FEATURES, MODEL_NAME, TOKENIZER_NAME  # noqa: E402
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402


_PREDICTOR_CACHE: dict[tuple[str, str, str, int], object] = {}


def _load_predictor(model_name: str, tokenizer_name: str, *, device: str = "cpu", max_context: int = 512):
    key = (model_name, tokenizer_name, device, max_context)
    if key not in _PREDICTOR_CACHE:
        tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
        model = Kronos.from_pretrained(model_name)
        tokenizer.eval()
        model.eval()
        _PREDICTOR_CACHE[key] = KronosPredictor(model, tokenizer, device=device, max_context=max_context)
    return _PREDICTOR_CACHE[key]


@dataclass
class KronosForecastAdapter:
    model_name: str = MODEL_NAME
    tokenizer_name: str = TOKENIZER_NAME
    device: str = "cpu"
    max_context: int = 512
    model_load_seconds: float | None = None

    def predict(self, context: pd.DataFrame, future: pd.DataFrame, *, horizon_bars: int, settings: dict[str, object]) -> tuple[pd.DataFrame, float]:
        model_name = str(settings.get("model_checkpoint", self.model_name))
        tokenizer_name = str(settings.get("tokenizer_checkpoint", self.tokenizer_name))
        effective_lookback = int(settings.get("effective_lookback_bars", len(context)))
        history = context.tail(effective_lookback).rename(columns={"timestamp": "timestamps"}).copy()
        if self.model_load_seconds is None:
            started = time.perf_counter()
            _load_predictor(model_name, tokenizer_name, device=self.device, max_context=self.max_context)
            self.model_load_seconds = time.perf_counter() - started
        predictor = _load_predictor(model_name, tokenizer_name, device=self.device, max_context=self.max_context)
        future_timestamps = future["timestamp"].reset_index(drop=True)
        started = time.perf_counter()
        with torch.no_grad():
            forecast = predictor.predict(
                df=history[FEATURES],
                x_timestamp=history["timestamps"],
                y_timestamp=future_timestamps,
                pred_len=horizon_bars,
                T=float(settings.get("temperature", 1.0)),
                top_k=int(settings.get("top_k", 0)),
                top_p=float(settings.get("top_p", 0.9)),
                sample_count=int(settings.get("sample_count", 1)),
                verbose=False,
            )
        seconds = time.perf_counter() - started
        forecast = forecast.reset_index(drop=True)
        forecast.insert(0, "timestamp", future_timestamps.reset_index(drop=True))
        return forecast, seconds


class FakeForecastAdapter:
    """Fast deterministic adapter for integration tests and dry runs."""

    model_name = "fake_context_only_linear"

    def predict(self, context: pd.DataFrame, future: pd.DataFrame, *, horizon_bars: int, settings: dict[str, object]) -> tuple[pd.DataFrame, float]:
        closes = context["close"].astype(float)
        step = float(closes.tail(20).diff().dropna().mean())
        last = float(closes.iloc[-1])
        values = [last + step * (index + 1) for index in range(horizon_bars)]
        return pd.DataFrame({"timestamp": future["timestamp"].reset_index(drop=True), "close": values}), 0.0
