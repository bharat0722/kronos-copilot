# Test 1: Unseen Real-World Stress

Technical verdict: PASS
Symbol: BAJFINANCE.NS; highest realized volatility among the two eligible prescribed candidates.
Market closed. Latest returned completed bar: 2026-10-09T15:15:00+05:30
Default Kronos-base: 400 context bars, 75 predicted bars, T=1.0, top_k=0, top_p=0.9, one sample, CPU.
Bull/Bear/Risk accepted first attempt; snapshot e46ff36ea8c01dcbb4a6193b48d00c27116d55737a2c214b606aa5f38f369153
News retrieval FRESH (Tavily); impact INSUFFICIENT_EVIDENCE, therefore research quality DEGRADED.
Raw Kronos bullish; technical trend bearish. Fusion MIXED, LOW support, HIGH risk.
Technical evidence is STALE under wall-clock fusion and not an eligible current primary directional conflict. Its opposing direction and the agents' conflict qualifications remain visible.
No calibrated probability or forecast-accuracy claim is made.

## Deterministic Selection Audit

### Bear
Available IDs: context.directional_conflict, kronos.config, kronos.direction, kronos.forecast_final_close, kronos.forecast_pct_change, kronos.last_observed_close, kronos.model_id, market_data.quality, news.article.0, news.article.1, news.article.2, news.article.3, news.article.4, news.event.0, news.event.1, news.event.2, news.event.3, news.event.4, news.evidence_status, news.impact_score, news.uncertainty, technicals.indicator.0, technicals.indicator.1, technicals.indicator.10, technicals.indicator.11, technicals.indicator.2, technicals.indicator.3, technicals.indicator.4, technicals.indicator.5, technicals.indicator.6, technicals.indicator.7, technicals.indicator.8, technicals.indicator.9, technicals.regime, technicals.trend
| Selected ID | Label | Use | Direction | Quality | Freshness | Allowed role modes |
| --- | --- | --- | --- | --- | --- | --- |
| technicals.trend | Technical evidence | SUPPORT | BEARISH | PASS | FRESH | SUPPORT |
| technicals.indicator.0 | EMA20 | SUPPORT | BEARISH | PASS | FRESH | SUPPORT |
| kronos.direction | Kronos forecast | COUNTER | BULLISH | PASS | FRESH | COUNTER, RISK |

### Bull
Available IDs: context.directional_conflict, kronos.config, kronos.direction, kronos.forecast_final_close, kronos.forecast_pct_change, kronos.last_observed_close, kronos.model_id, market_data.quality, news.article.0, news.article.1, news.article.2, news.article.3, news.article.4, news.event.0, news.event.1, news.event.2, news.event.3, news.event.4, news.evidence_status, news.impact_score, news.uncertainty, technicals.indicator.0, technicals.indicator.1, technicals.indicator.10, technicals.indicator.11, technicals.indicator.2, technicals.indicator.3, technicals.indicator.4, technicals.indicator.5, technicals.indicator.6, technicals.indicator.7, technicals.indicator.8, technicals.indicator.9, technicals.regime, technicals.trend
| Selected ID | Label | Use | Direction | Quality | Freshness | Allowed role modes |
| --- | --- | --- | --- | --- | --- | --- |
| kronos.direction | Kronos forecast | SUPPORT | BULLISH | PASS | FRESH | SUPPORT, RISK |
| context.directional_conflict | Conflicting primary directions | RISK | NON_DIRECTIONAL | WARN | FRESH | RISK |
| technicals.indicator.4 | RSI14 | RISK | NEUTRAL | PASS | FRESH | RISK |

### Risk
Available IDs: context.directional_conflict, kronos.config, kronos.direction, kronos.forecast_final_close, kronos.forecast_pct_change, kronos.last_observed_close, kronos.model_id, market_data.quality, news.article.0, news.article.1, news.article.2, news.article.3, news.article.4, news.event.0, news.event.1, news.event.2, news.event.3, news.event.4, news.evidence_status, news.impact_score, news.uncertainty, technicals.indicator.0, technicals.indicator.1, technicals.indicator.10, technicals.indicator.11, technicals.indicator.2, technicals.indicator.3, technicals.indicator.4, technicals.indicator.5, technicals.indicator.6, technicals.indicator.7, technicals.indicator.8, technicals.indicator.9, technicals.regime, technicals.trend
| Selected ID | Label | Use | Direction | Quality | Freshness | Allowed role modes |
| --- | --- | --- | --- | --- | --- | --- |
| context.directional_conflict | Conflicting primary directions | RISK | NON_DIRECTIONAL | WARN | FRESH | RISK |
| news.event.0 | News context | RISK | NEUTRAL | PASS | UNKNOWN | RISK |
| news.evidence_status | News context | RISK | NON_DIRECTIONAL | PASS | UNKNOWN | RISK |
| technicals.trend | Technical evidence | RISK | BEARISH | PASS | FRESH | RISK |

## Scope and Limitations
- Latest provider bars stop at 15:15 IST; no missing closing bars were invented
- Closed-session technical evidence is STALE in wall-clock fusion; V4 catalogue freshness is relative to its technical as-of
- Fresh news retrieval did not yield sufficient scored event context: impact INSUFFICIENT_EVIDENCE
- Optional model explanations are unverified presentation, never authoritative facts
Desktop/iPad/phone responsive QA uses the actual application code and saved real API-compatible outputs, not synthetic scaffolding. All additional browser provider calls are blocked.
The collector field-name incident was recovered from durable state with no reruns. News stage at completion is reconstructed from retained response state, explicitly labelled in JSON.
Full source, selected evidence lineage, resolved backend facts, stage health, and attempts are in test1_live_stress.json.
