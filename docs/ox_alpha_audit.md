---
model: stealth/ox-alpha
audit_datetime_ist: 2026-08-22T23:17:20+05:30
files_supplied: 22
approx_context_tokens: 79814
request_tokens: 79281
completion_tokens: 3176
total_tokens: 82457
cost: 0
finish_reason: stop
---

# Ox Alpha Deep Audit - Kronos Copilot

## Files Supplied
- app/server.py (42877 chars)
- src/forecast_config.py (4799 chars)
- src/first_forecast.py (7823 chars)
- app/dashboard.html (17245 chars)
- app/dashboard.css (29559 chars)
- app/dashboard.js (58793 chars)
- outputs/forecast_summary.json (1511 chars)
- vendor/Kronos-master/README.md (16234 chars)
- vendor/Kronos-master/model/kronos.py (30125 chars)
- vendor/Kronos-master/model/module.py (22856 chars)
- vendor/Kronos-master/examples/prediction_example.py (2377 chars)
- vendor/Kronos-master/examples/prediction_batch_example.py (2312 chars)
- vendor/Kronos-master/examples/run_backtest_kronos.py (15048 chars)
- vendor/Kronos-master/tests/test_kronos_regression.py (5326 chars)
- vendor/Kronos-master/finetune_csv/README.md (3959 chars)
- vendor/Kronos-master/finetune_csv/finetune_base_model.py (19127 chars)
- vendor/Kronos-master/finetune_csv/finetune_tokenizer.py (13731 chars)
- vendor/Kronos-master/finetune/train_predictor.py (9792 chars)
- vendor/Kronos-master/finetune/train_tokenizer.py (11182 chars)
- README.md (726 chars)
- requirements.txt (71 chars)
- Start Kronos Copilot.bat (1706 chars)

## Audit Report

# Kronos Copilot — Deep Architecture & Quality Audit

## 1. Executive Summary

Kronos Copilot is a well-structured, Demo Day–ready local forecasting dashboard. The core separation of concerns is **correct and verifiable**: Yahoo Finance supplies data, Kronos-base runs inference locally, and OpenAI only explains an already-completed forecast via a compact JSON summary. The forecast pipeline never touches OpenAI.

The strongest aspects are the cache-first design (forecast caching keyed on data hash + sampling params, explanation caching keyed on a fingerprint), the trading-session timestamp logic that correctly skips closed-market hours, and the frontend's stale-result protection (request sequencing + fingerprint binding).

Main risks: the server binds to `0.0.0.0` (LAN-exposed) with no auth; the API key lives in `.env.local` loaded into process env (acceptable locally but fragile); `yfinance` network calls can hang or fail silently during a live demo; and the 5 MB CSV limit plus 400-bar requirement create predictable user-facing failure modes. None of these require architectural change — they're hardening items.

**Overall verdict: solid MVP, low-risk architecture, ready for demo with a few targeted fixes.**

---

## 2. Current Architecture Explained Simply

```
Browser (dashboard.html/js/css)
   │
   ▼
Local Python server (app/server.py, port 8000)
   │
   ├── GET/POST /api/* endpoints ──► run_forecast() / run_validation()
   │        │
   │        ├── fetch_live_market_data() ──► yfinance (Yahoo) ──► 5-min OHLCV bars
   │        │
   │        ├── validate_market_csv() / normalize_market_data()
   │        │
   │        ├── predict_with_kronos() ──► vendor/Kronos-master (local PyTorch, CPU)
   │        │      └── outputs/forecast.csv + forecast_summary.json
   │        │
   │        └── build_dashboard_payload() ──► chart points, timing, freshness
   │
   ├── /api/symbol-search ──► yf.Search (NSE/BSE equity filter)
   │
   └── /api/explanation ──► optional GPT-5-mini call on compact summary
          └── cached in outputs/explanation.json by fingerprint
```

Key layers:
1. **Data acquisition** — Yahoo live fetch or CSV upload, normalized to IST timestamps.
2. **Forecast engine** — Kronos-base reads 400 bars, predicts 24/75/120 five-minute bars using market-session-aware future timestamps.
3. **Summary layer** — small JSON (`forecast_summary.json`) designed for cheap AI consumption.
4. **Explanation layer** — optional, cache-first, fingerprint-bound to one exact forecast.
5. **Presentation layer** — canvas chart, metric cards, validation panel.

---

## 3. What Works Well

- **Clean three-way separation**: `run_kronos_forecast()` has zero OpenAI imports; `_generate_explanation()` never touches Kronos or yfinance for values.
- **Cache-first everywhere**: forecasts cached by SHA-256 of normalized data + sampling params (`forecast_cache_key`); explanations cached by `summary_fingerprint`. Re-runs of identical requests cost nothing.
- **Fingerprint integrity**: explanations are bound to `summary_fingerprint`; if the forecast changes mid-generation, generation aborts (`generate_explanation` re-checks).
- **Session-aware timestamps**: `next_valid_market_bar()` correctly skips weekends, jumps past 15:30 to next weekday 9:15, aligns to 5-minute grid. The "session" horizon (75 bars = exactly one NSE session) is elegant.
- **Stale-result protection**: request sequence IDs, AbortControllers, and fingerprint checks prevent old responses overwriting new ones.
- **Accessibility**: skip link, ARIA combobox pattern for search, sr-only chart summary text, reduced-motion/transparency/contrast media queries, keyboard-navigable results list.
- **Validation mode**: honest self-evaluation (MAE/RMSE/directional agreement) shown transparently — good trust signal for judges.
- **Honest disclaimers**: "not financial advice," delayed-data notices, holiday caveat all present.

---

## 4. Findings Table

| # | Severity | Finding | Evidence | Impact | Recommendation |
|---|----------|---------|----------|--------|----------------|
| F1 | **High** | Server binds `0.0.0.0` with no auth | `ThreadingHTTPServer(("0.0.0.0", 8000), ...)` | Anyone on same Wi-Fi can trigger forecasts (CPU burn), read files served from project root (SimpleHTTPRequestHandler serves entire project dir including `.env.local`, `outputs/`, `data/`) | Bind `127.0.0.1` by default; if LAN needed, add a token check or at minimum exclude sensitive paths |
| F2 | **High** | Static file serving exposes secrets | `directory=str(PROJECT_ROOT)` serves everything | `http://<ip>:8000/.env.local` returns your OpenAI key to any LAN client | Serve only `app/` directory, or add path allowlist in `do_GET` before `super().do_GET()` |
| F3 | **Medium** | No timeout on Kronos inference; FORECAST_LOCK serializes all requests | `with FORECAST_LOCK:` around full inference (~40s observed) | Second user/request blocks indefinitely; demo feels frozen | Add a lock-acquire timeout with friendly "another forecast is running" error |
| F4 | **Medium** | yfinance calls have inconsistent failure handling | `yf.Ticker(...).history(...)` wrapped, but `yf.Search` errors swallowed silently (`except Exception: pass`) | Search silently returns only direct-match result; confusing UX | Log the exception; return partial result with a note |
| F5 | **Medium** | CSV size limit message vs actual behavior | 5 MB limit checked after reading whole body into memory | Large uploads still consume memory before rejection | Check Content-Length header first |
| F6 | **Low** | `MODEL_NAME = "gpt-5-mini"` hardcoded; no model fallback | `_generate_explanation` | If model name invalid/deprecated, explanation silently fails (handled gracefully, but no diagnostics) | Move to config constant with clear error surface |
| F7 | **Low** | Explanation POST catches bare `Exception` | `except Exception:` → generic 502 | Real errors (quota, auth) indistinguishable to user | Catch specific OpenAI exceptions, map to messages |
| F8 | **Low** | `SYMBOL_SEARCH_CACHE` unbounded growth | dict grows per query | Trivial memory leak over long sessions | Cap size or rely on TTL eviction sweep |
| F9 | **Low** | Frontend `formatPrice` uses `state.currentResult` default | stale currency formatting possible mid-transition | Cosmetic | Pass explicit result always (mostly done already) |
| F10 | **Info** | `requirements.txt`: `openai==3.3.1` is very old pin style; yfinance version may drift APIs | requirements.txt | Reproducibility risk on fresh install | Pin exact versions verified working |

---

## 5. Kronos Usage Review

Compared against the official reference:

✅ **Correct usage:**
- Loads `KronosTokenizer` + `Kronos` from correct HF repos, matching tokenizer (`Kronos-Tokenizer-base`) for base model.
- `max_context=512` matches official guidance; lookback of 400 stays safely under it.
- Feature order `['open','high','low','close','volume','amount']` matches predictor expectations.
- Uses `predictor.predict(df=..., x_timestamp=..., y_timestamp=..., pred_len=..., T, top_k, top_p, sample_count)` — exact official signature.
- Normalization/denormalization handled internally by `KronosPredictor` (correct — not reimplemented).
- Model cached in `_MODEL_CACHE` so repeat forecasts don't reload weights (important: load takes significant time).

⚠️ **Observations:**
- Runs on CPU (`device="cpu"` hardcoded). Official code auto-detects CUDA/MPS. On a laptop this means ~40s inference (matches saved summary). Acceptable for demo, but consider auto-detect for speed if GPU available.
- `sample_count=1` default is fine; experimental settings exist but UI doesn't expose them (fine for MVP).
- Timestamps passed as tz-aware IST Series — `calc_time_stamps` extracts minute/hour/weekday/day/month correctly regardless of tz.
- **No issue found where OpenAI could influence forecast values.** Verified: `first_forecast.py` imports nothing from OpenAI; the explanation endpoint reads only `outputs/*.json`.

---

## 6. Data and Timestamp Review

- **Session logic is correct**: `next_valid_market_bar` handles pre-open (→9:15), post-close (→next weekday 9:15), weekends, and 5-minute grid alignment. 75 bars × 5 min = 375 min = 6h15m = exactly one NSE session (9:15–15:30). ✅
- **Overnight rollover**: `build_forecast_timestamps` naturally produces multi-day sequences when horizon crosses sessions; frontend `forecastSessionParts` splits them and labels "Market closed" between sessions. Chart does not draw connecting lines across gaps in line mode (`drawPolyline` checks gap > 5 min). ✅
- **Trading-time view**: closed hours omitted rather than shown as flat lines — matches stated behavior. ✅
- **Timezone discipline**: all timestamps coerced to Asia/Kolkata via `coerce_market_timestamps`; Yahoo UTC converted properly. CSV uploads get localized if naive. ✅
- **Minor**: exchange holidays are *not* modeled (acknowledged in UI note). A 75-bar forecast started Thursday afternoon will project Friday timestamps even if Friday is a holiday. Acceptable with the existing disclaimer; a static NSE holiday list would be a cheap improvement.
- **Validation alignment**: predicted vs actual joined on timestamps with inner merge — robust to mismatched bars, raises clear error when empty. ✅

---

## 7. Frontend/Dashboard Review

**State integrity:** Strong. Request-sequence guards (`requestId !== state.requestSequence`) on every async completion; AbortController cancels superseded fetches; pending-key dedup prevents double-submit; previous result preserved and labeled during loading ("Previous forecast" badge). Fingerprint binding prevents explanation/result mismatch.

**Chart semantics:** Canvas-based candles/line toggle, volume subpanel, dashed prediction boundary, forecast region shading, direction-colored forecast candles, actual-future overlay in validation mode. Line mode correctly breaks polylines across session gaps. Axis labels use tabular numerals; responsive insets for narrow widths.

**Accessibility:** Good — combobox/listbox ARIA pattern with arrow-key navigation, aria-live regions for status, sr-only chart description that includes session breakdown and prices, focus-visible rings, skip link, theme switch with aria-pressed.

**Responsiveness:** Four breakpoints down to 480px; chart switches aspect ratio then fixed height; control grid collapses sensibly; touch targets ≥44px on mobile.

**Minor issues:**
- `updateForecastButtons` label logic has redundant branches (`pendingLive ? actionLabel : actionLabel`) — harmless dead code.
- Chart redraws fully on every theme change and resize — fine at this scale.
- No error boundary if canvas context unavailable (extremely unlikely).

---

## 8. Security and API-Cost Review

**Secret leakage — the top concern:**
- `.env.local` holds `OPENAI_API_KEY`, loaded server-side only (good — never sent to browser).
- **But** the static handler serves the whole project root (F2). One HTTP request to `/.env.local` leaks the key to anyone on the LAN. This is the single most important fix.

**Cost controls — well designed:**
- Forecast: zero API cost (local Kronos).
- Explanation: max_output_tokens=180, minimal reasoning effort, compact input JSON, prompt-versioned cache, fingerprint-bound cache. Worst case per unique forecast: one small call. Cache hit path costs nothing.
- No background/prefetch API calls found. Explanation only fires on explicit button click or explicit cached-load GET (which doesn't call OpenAI).
- **Verdict: accidental API spend risk is LOW**, contingent on fixing F2.

**Other:**
- Ticker regex validation blocks injection-style inputs into yfinance.
- Filename sanitized via `Path(...).name`.
- CSV parsed with pandas (no eval/code paths).
- No CSRF concern (local tool, JSON-only POSTs).

---

## 9. Demo Day Readiness Review

**Will likely go well if:**
- Pre-warm the model before the audience arrives (first load downloads weights + ~40s inference).
- Use a cached forecast for the opening demo (`cache_hit: true` shows instantly).
- Have a pre-uploaded CSV as backup if venue Wi-Fi blocks Yahoo.

**Predictable failure modes:**
1. **Venue Wi-Fi blocks/breaks yfinance** → live forecast fails. Mitigation: CSV backup ready.
2. **Second request during 40s inference** appears frozen (F3). Mitigation: status messaging exists; avoid triggering concurrent runs.
3. **Holiday-timestamp confusion** if asked "why does it show Saturday?" — the UI copy handles this; know the answer.
4. **LAN snooping** if demoing on shared Wi-Fi (F1/F2) — fix before demoing anywhere public.
5. **Symbol search returning odd results** for obscure names — direct-symbol fallback covers tickers; company-name searches depend on Yahoo.

**Strengths for judges:** validation metrics panel, honest uncertainty language, local-inference story ("runs on this laptop"), cost-conscious design narrative.

---

## 10. Top 5 Next Actions

1. **Fix static file serving scope (F2/F1)** — serve only `app/` statically, bind to `127.0.0.1` unless LAN mode explicitly enabled. Highest security value, ~10 lines of change.
2. **Add a lock timeout + concurrent-request message (F3)** — return "A forecast is already running, please wait" instead of blocking, so the UI never looks frozen.
3. **Pre-demo warmup script** — a small script/runbook that loads the model, runs one cached forecast, and verifies `/api/dashboard` returns 200 before doors open.
4. **Add a bundled sample CSV + one-click "Load sample" button** — guarantees a working demo without network dependency, showcasing CSV mode deliberately rather than as a fallback.
5. **Surface yfinance/search failures distinctly (F4/F7)** — log swallowed exceptions and differentiate quota/auth/network errors in the explanation endpoint, so any live failure is diagnosable in seconds.

*None of these change the MVP architecture — they harden what already works.*
