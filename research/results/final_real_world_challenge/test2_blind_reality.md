# Test 2: Blind Reality

AXISBANK.NS; all three timestamp-selected windows retained.
News excluded to prevent leakage. Default horizon unchanged; 24-bar metrics reuse the same prediction.
Workers received only 400 visible bars. Forecasts, baselines, agents and fusion were persisted and hashed before each scoring-stage target read.
Source gaps are not imputed. Metrics use identical observed timestamps for Kronos and baselines, with real production endpoint bars.

## Window 1
Cutoff: 2026-09-30T15:15:00+05:30
Team: 3/3; state COMPLETE
Coverage: 73/75; freeze ce62b6d95ff63045e10dcf2cd76b039ee12b75601a9a8157a394d3c15021781b
Predicted return -0.772439%; actual -0.725940%; direction match True.
MAE 9.733877; RMSE 11.131305; MAPE 0.791347%; SMAPE 0.795455%; endpoint error 0.046839%.
Fusion before reveal: MIXED; directional match None
| Method | MAE | RMSE | MAPE % | SMAPE % | Final error % |
| --- | ---: | ---: | ---: | ---: | ---: |
| drift | 16.038835 | 16.493498 | 1.305533 | 1.314606 | 1.441718 |
| kronos | 9.733877 | 11.131305 | 0.791347 | 0.795455 | 0.046839 |
| momentum | 6.271220 | 7.495720 | 0.508984 | 0.510566 | 0.402929 |
| persistence | 6.705479 | 7.395009 | 0.545189 | 0.546058 | 0.731248 |

## Window 2
Cutoff: 2026-10-05T15:15:00+05:30
Team: 2/3; state PARTIAL
Coverage: 73/75; freeze e30315dcf4e94b21ea5020af549cae4d87cafd691dae51f4fb21d5b4634e7980
Predicted return -0.359610%; actual 2.110952%; direction match False.
MAE 23.997350; RMSE 24.916638; MAPE 1.927486%; SMAPE 1.947696%; endpoint error 2.419487%.
Fusion before reveal: BEARISH; directional match False
| Method | MAE | RMSE | MAPE % | SMAPE % | Final error % |
| --- | ---: | ---: | ---: | ---: | ---: |
| drift | 47.879052 | 51.515034 | 3.844082 | 3.931557 | 6.147532 |
| kronos | 23.997350 | 24.916638 | 1.927486 | 1.947696 | 2.419487 |
| momentum | 23.576251 | 24.441105 | 1.893584 | 1.913022 | 2.402648 |
| persistence | 21.400055 | 22.083226 | 1.718927 | 1.734781 | 2.067312 |

## Window 3
Cutoff: 2026-10-07T15:10:00+05:30
Team: 2/3; state PARTIAL
Coverage: 72/75; freeze 9281e8ca1db73485d6bbc75d1f1928a10e343d5e19f820bd6c0f079df736d219
Predicted return -2.302930%; actual 0.064390%; direction match False.
MAE 14.979500; RMSE 18.651988; MAPE 1.204658%; SMAPE 1.213643%; endpoint error 2.365796%.
Fusion before reveal: BEARISH; directional match False
| Method | MAE | RMSE | MAPE % | SMAPE % | Final error % |
| --- | ---: | ---: | ---: | ---: | ---: |
| drift | 15.138546 | 16.678746 | 1.214879 | 1.223798 | 1.905813 |
| kronos | 14.979500 | 18.651988 | 1.204658 | 1.213643 | 2.365796 |
| momentum | 6.275461 | 6.951322 | 0.503524 | 0.504762 | 0.425805 |
| persistence | 4.458333 | 5.350029 | 0.357824 | 0.358319 | 0.064349 |

## Limits
- Source target coverage 73/75, 73/75, 72/75; real endpoints present; no imputation
- Cutoffs chosen from timestamp/count eligibility only; missing endpoints excluded before inference
- Current volatility symbol preselection is retrospective relative to historical cutoffs, as explicitly prescribed; not a prospective strategy backtest
- The historical online challenge checks input blinding, not global model-training membership or general predictive accuracy
- One rejected Bull perspective and one budget-blocked Risk perspective remain missing; fusion retains those missing markers
All 24-bar metrics and accepted pre-reveal selected IDs, facts, fusion lineage, diagnostics and omitted perspectives are retained in test2_blind_reality.json.
