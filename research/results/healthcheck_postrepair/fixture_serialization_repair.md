# Offline synthetic fixture serialization repair

Status: PASS. No live calls authorized or performed.

| Test | Old bytes | New bytes | Headroom to48000 | Preflight | Offline team | Fusion |
|---|---:|---:|---:|---|---|---|
| A | 51805 | 21420 | 26580 | PASS |3/3|PASS|
| B | 52083 | 21834 | 26166 | PASS |3/3|PASS|

## Measurement and production comparison

Exact wire is canonical JSON of snapshot_id,evidence,evidence_catalog. Catalog repeats source values intentionally; production serializer is unchanged. Before/after section byte allocation and percentages sum to exact payload sizes in fixture_byte_breakdown.json. No unmeasured claim of payload savings.

Saved real product reference inspected only for schema/counts/lengths: 31144 bytes,7 articles,12 indicators. No real content copied/transmitted/modified. Product MAX_EVENTS8. Old fixture25articles was an artificially enlarged stress fixture.

- unchanged_production_duplication: Evidence and evidence_catalog intentionally coexist. Removing catalog copy would change production, so retained.
- news_count: 25 inflated repeated bulletins ->8 unique stories, matching MAX_EVENTS8 and reference7; removed surplus repetitive context, not a required scenario.
- summaries: Repeated four/five-times sentences ->single concise distinct factual summaries, preserving partnership/weak discussion/caution.
- headlines_urls: Cross-article duplicates removed through distinct stories. Article/event/source URL copies retained where canonical production contract requires lineage.
- metadata: Canonical allowlist via create_content; no provider payload/log/large histories/full text.
- technicals: All12 implemented indicator names retained; current values,signal,strength,reason,regime/time/hash.
- forecast: Canonical model/config,lookback,horizon,current/final price,direction,percentage,fingerprint/hash.
- pipeline: Market quality/provider/capture/bronze/silver/gold references in wire; structured health in separate fusion META envelope.
- preferred_size: Below35k is intentional: preferred35-42k is not a minimum. Padding concise synthetic statements to match production narratives would reintroduce bloat. Rigor is coverage, not bytes.

## Preserved rigor

NormalA retains upward forecast, constructive technicals, positive and neutral factual company context. Bear may abstain; risk retains forecast uncertainty. No pathological normal-case conflict.

- FACT_vs_INTERPRETATION: Supported direct partnership fact vs unsupported demand fact; interpretation cannot masquerade as FACT.
- DIRECT_vs_DERIVED: Exact price/percentage/RSI values remain available; derived forecast and trend interpretations remain typed.
- mixed_family: Upward forecast vs bearish trend; explicit MULTI_SOURCE/MIXED risk claim and separate single-family observations.
- claim_splitting: Forecast,technical,news families retain separately addressable IDs.
- primary_conflict: Kronos up; technical trend bearish; positive news vs weak unconfirmed discussion.
- uncertainty: HIGH_VOLATILITY, neutral descriptive indicators, weak news, unavailable historical confidence calibration.
- numerical_grounding: RSI44 vs invalid62/44%, forecast1.2%, observed100/final101.2; no unit relaxation.
- risk: Cross-source conflict and single-family event caution, no invented downside catalyst.

All6 agent families remain. Both use production create_content and exact AgentTeam.preflight, agent_output_v2, gpt-5-mini,Bullv7/Bearv6/Riskv6,cap1600,loop1,retry1,toolsNONE. No prompts/validators/config/production code changes. No invented calibrated confidence or performance.

## Offline validation

231passed,0failed,1skipped (opt-in liveYahoo).14new fixture tests. External DNS/connections blocked;0attempts escaped. Both frozen fixtures separately traversed mocked SDK response -> production parse/typed validation/grounding -> durable ledger -> cache -> reload -> deterministic fusion. Mock outputs are NOT live confirmation and cannot satisfy future provider gate.

Boundary tests47999/48000eligible and48001/50000blocked. Covered supported/unsupported qualitative facts,interpretation mislabel,numerical values/units,wrong/nonexistent IDs,mixed-family declarations,split claims,missing-news !=neutral,staleguard,snapshot-specific cache identity.

Fusion before/after agent inputs changes cache identity; subsequent unchanged input hits cache. All3derivedagent sources appear, lineage persists, Bconflicts remain, source evidence unchanged. Mock teamdurableCOMPLETE,rows3,ledgersPASS/STORED.

## Frozen inputs

TestA: `research/tests/fixtures/dual_live_retest_A_v2.json`

Snapshot: `b26ba306eb25260085510a6bea122b165c9c247dd6d53281bb8997ae3838f0f5`

WireSHA256: `4e58162e73dba05ee27e714774b57ef9ff952a85c6c99c0a64a342e187ccd328`

FileSHA256: `1eadc0d2f6b8975622c1289fa258a1dab34726dca5fd7459f8c15627b580f105`

TestB: `research/tests/fixtures/dual_live_retest_B_v2.json`

Snapshot: `f4a93fb9f8bd5268693700832d23610fb1e38e6787a7604e75bccc33963bc7a4`

WireSHA256: `c8a08c72ea45b47df31a8cc6f45881b0d41ca51b5fdfde8695959a10cb2bb19f`

FileSHA256: `79ba7b858c489828e742ac2117f07a9f88b9640a1d9f78b2857e2d632975e595`

Portable builder and JSON fixtures live under research/tests/fixtures, without machine paths/private data. Same fixed as_of produces identical bytes/hash/identity. Freshness timestamps are intentionally part of the frozen definition; the one-hour production guard is NOT bypassed. If authorization arrives after expiry, do not edit frozen files; stop/re-freeze explicitly before execution with a new manifest and reviewed hashes.

Historical blocked reports remain untouched. Main product live pointer/cache/budget not changed by synthetic mocks, which use isolated offline stores. No Gitcommit/push; no Monadwork. All providers/inference/training/validation/locked targets:0.

Dual live retest ready:YES, subject to fresh authorization and pre-execution freshness/budget recheck. This is NOT MonadGREEN or proof of actual provider recovery.

Next action: obtain fresh authorization for the two rigorous live synthetic three-agent retests using the frozen repaired fixture hashes. Do not execute in this task.
