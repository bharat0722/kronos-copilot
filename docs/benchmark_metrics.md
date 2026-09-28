# Benchmark Metrics

## MAE

Mean absolute error: `mean(abs(predicted_close - actual_close))`. Lower is better. Units are price units.

## RMSE

Root mean squared error: `sqrt(mean(error^2))`. Lower is better. Penalizes large misses more than MAE.

## MAPE

Mean absolute percentage error: `mean(abs(error / actual_close)) * 100`. Lower is better. It is unstable when actual values are near zero, so it should not be used alone.

## sMAPE

Symmetric MAPE: `mean(abs(error) / ((abs(actual) + abs(predicted)) / 2)) * 100`. Lower is better. It is less one-sided than MAPE but still has edge cases.

## MASE

Mean absolute scaled error. Phase 1 scales MAE by the in-context one-step naive error. `MASE < 1` can indicate improvement over that in-sample naive scale.

## Directional Match

Whether the final predicted move from the cutoff has the same sign as the actual final move. This is not the same thing as price accuracy.

## Step Directional Match

The percentage of non-flat future steps where predicted and actual step directions agree.

## Correlation

Pearson correlation between predicted and actual close paths. High correlation can coexist with biased price levels, so use it alongside error metrics.

## Range And Volatility

Actual and predicted close range and return volatility compare path shape. They do not prove tradability or confidence.

## Phase 1A.2 Additions

Reports now include n, mean, median, standard deviation, min, max, normalized MAE, return error, return correlation where valid, range error, volatility error, and optional OHLC/volume errors when those fields exist in both prediction and actual paths.

Kronos-vs-baseline comparisons are paired by the same symbol, horizon, and cutoff. For error metrics, delta means `Kronos error - baseline error`; negative means Kronos was better on that window.

Bootstrap confidence intervals are deterministic and seed-controlled. They are suppressed as `INSUFFICIENT_SAMPLE` below the configured minimum sample threshold. Overlapping windows are correlated, so bootstrap intervals may overstate certainty until a later block-bootstrap method is added.
