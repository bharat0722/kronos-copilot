"""Central benchmark metrics with explicit definitions."""

from __future__ import annotations

import math

import pandas as pd


def aligned(predicted: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    left = predicted.rename(columns={"close": "predicted_close"})
    right = actual.rename(columns={"close": "actual_close"})
    joined = left[["timestamp", "predicted_close"]].merge(right[["timestamp", "actual_close"]], on="timestamp", how="inner")
    joined["predicted_close"] = pd.to_numeric(joined["predicted_close"], errors="coerce")
    joined["actual_close"] = pd.to_numeric(joined["actual_close"], errors="coerce")
    joined = joined.dropna()
    if joined.empty:
        raise ValueError("Predicted and actual closes could not be aligned.")
    return joined


def mase_scale(context: pd.DataFrame) -> float | None:
    closes = pd.to_numeric(context["close"], errors="coerce").dropna()
    diffs = closes.diff().abs().dropna()
    scale = float(diffs.mean()) if not diffs.empty else 0.0
    return scale if scale > 0 else None


def close_metrics(predicted: pd.DataFrame, actual: pd.DataFrame, context: pd.DataFrame) -> dict[str, object]:
    data = aligned(predicted, actual)
    error = data["predicted_close"] - data["actual_close"]
    abs_error = error.abs()
    mae = float(abs_error.mean())
    rmse = math.sqrt(float((error ** 2).mean()))
    denominators = data["actual_close"].abs()
    mape = float((abs_error / denominators).mean() * 100) if (denominators > 0).all() else None
    smape_den = (data["actual_close"].abs() + data["predicted_close"].abs()) / 2
    smape = float((abs_error / smape_den).mean() * 100) if (smape_den > 0).all() else None
    scale = mase_scale(context)
    mase = float(mae / scale) if scale else None
    last_close = float(context["close"].iloc[-1])
    actual_final = float(data["actual_close"].iloc[-1])
    predicted_final = float(data["predicted_close"].iloc[-1])
    actual_direction = "up" if actual_final >= last_close else "down"
    predicted_direction = "up" if predicted_final >= last_close else "down"
    actual_steps = data["actual_close"].diff().dropna()
    predicted_steps = data["predicted_close"].diff().dropna()
    mask = actual_steps.ne(0) & predicted_steps.ne(0)
    step_directional_match_pct = float((actual_steps[mask].gt(0) == predicted_steps[mask].gt(0)).mean() * 100) if mask.any() else None
    corr = None
    if data["actual_close"].std(ddof=0) > 0 and data["predicted_close"].std(ddof=0) > 0:
        corr = data["actual_close"].corr(data["predicted_close"])
    actual_return = (actual_final - last_close) / last_close if last_close else None
    predicted_return = (predicted_final - last_close) / last_close if last_close else None
    return_error = abs(predicted_return - actual_return) if actual_return is not None and predicted_return is not None else None
    return_corr = None
    actual_returns = data["actual_close"].pct_change().dropna()
    predicted_returns = data["predicted_close"].pct_change().dropna()
    if len(actual_returns) and actual_returns.std(ddof=0) > 0 and predicted_returns.std(ddof=0) > 0:
        return_corr = actual_returns.corr(predicted_returns)
    actual_vol = float(actual_returns.std(ddof=0)) if len(actual_returns) else 0.0
    predicted_vol = float(predicted_returns.std(ddof=0)) if len(predicted_returns) else 0.0
    result = {
        "compared_bars": int(len(data)),
        "mae": mae,
        "close_mae": mae,
        "normalized_mae": mae / abs(last_close) * 100 if last_close else None,
        "rmse": rmse,
        "mape": mape,
        "smape": smape,
        "mase": mase,
        "final_error": abs(predicted_final - actual_final),
        "final_error_pct": abs(predicted_final - actual_final) / abs(actual_final) * 100 if actual_final else None,
        "total_return_error": return_error,
        "actual_return": actual_return,
        "predicted_return": predicted_return,
        "directional_match": predicted_direction == actual_direction,
        "actual_direction": actual_direction,
        "predicted_direction": predicted_direction,
        "step_directional_match_pct": step_directional_match_pct,
        "correlation": None if corr is None or pd.isna(corr) else float(corr),
        "return_correlation": None if return_corr is None or pd.isna(return_corr) else float(return_corr),
        "actual_range": float(data["actual_close"].max() - data["actual_close"].min()),
        "predicted_range": float(data["predicted_close"].max() - data["predicted_close"].min()),
        "range_error": abs(float(data["predicted_close"].max() - data["predicted_close"].min()) - float(data["actual_close"].max() - data["actual_close"].min())),
        "actual_volatility": actual_vol,
        "predicted_volatility": predicted_vol,
        "volatility_error": abs(predicted_vol - actual_vol),
    }
    for column in ("open", "high", "low", "volume"):
        if column in predicted.columns and column in actual.columns:
            joined = predicted[["timestamp", column]].rename(columns={column: f"predicted_{column}"}).merge(
                actual[["timestamp", column]].rename(columns={column: f"actual_{column}"}),
                on="timestamp",
                how="inner",
            )
            if not joined.empty:
                result[f"{column}_mae"] = float((joined[f"predicted_{column}"] - joined[f"actual_{column}"]).abs().mean())
    if all(key in result for key in ("open_mae", "high_mae", "low_mae", "close_mae")):
        result["ohlc_aggregate_error"] = float((result["open_mae"] + result["high_mae"] + result["low_mae"] + result["close_mae"]) / 4)
    return result
