# One bounded live three-agent confirmation

## Verdict
**FAIL. Team 0/3, FAILED. Monad readiness RED; permission NO.**
Exactly one production AgentTeam.run, six SDK attempts and six HTTP requests (two per role). No extra recovery workflow or calls. Validation correctly prevented rejected output from being published or cached.

## Fixture and contract
Fixture: `synthetic_production_v1_TESTCO`. Snapshot: `141d6b9cb3e9868a2d68b81497af9cc2147801ec92120e992444d2ca0407b1cf`.
Production-sized, fully synthetic NSE:TESTCO; 25 fictional articles with example.org links, never fetched. Synthetic metadata labels such as Yahoo are fixture values, not actual provider calls.
Model gpt-5-mini; provider returned gpt-5-mini-2025-08-07. Prompts Bull v6, Bear v5, Risk v5. agent_output_v2, output ceiling1600, retry1 per role, loop1, toolsNONE, SDK retries0. Input wire41477 bytes, below48000.
Existing harness/validators/current prompts used without edits. Synthetic current pointer/cache/ledger isolated from the real market product view; existing production daily SQLite budget reused without reset. Budget 0 -> 6 /12 for 2026-10-09.

## Live results
| Role | Result | Attempts | Input tokens | Output tokens | Response / finish reason | Failure stage |
|---|---|---|---|---|---|---|
| Bear | FAIL | 2 | 24704 | 1179 | completed / null | CLAIM_VALIDATION |
| Bull | FAIL | 2 | 24704 | 1031 | completed / null | CLAIM_VALIDATION |
| Risk | FAIL | 2 | 28048 | 1338 | completed / null | CLAIM_VALIDATION |

Role token totals sum both attempts. Six response output counts: 584,447,581,598,746,592; every attempt below1600. Total input77456, output3548, tokens81004. API cost **UNKNOWN**: no pricing/account calls made. Responses status was completed; separate finish reason was null, not an invented stop value.

## Precise failure evidence
- bull attempt 1, `key_factors.0`: Technicals.trend is labeled bullish in the snapshot.
  Reason: `unsupported_direct_fact`; IDs: technicals.trend.
- bull attempt 2, `key_factors.0`: Technicals block lists trend as 'bullish' and multiple indicators report 'bullish' signals.
  Reason: `unsupported_direct_fact`; IDs: technicals.trend, technicals.indicator.0.
- bear attempt 1, `key_factors.0`: Multiple technical indicators are labeled bullish in the snapshot.
  Reason: `unsupported_direct_fact`; IDs: technicals.indicator.0, technicals.indicator.1, technicals.indicator.2.
- bear attempt 2, `key_factors.0`: Multiple technical indicators are marked bullish in the snapshot.
  Reason: `unsupported_direct_fact`; IDs: technicals.indicator.0, technicals.indicator.1, technicals.indicator.2.
- risk attempt 1, `risk_factors.0`: Model forecast up is contradicted by research view stating 'Conflicting evidence'.
  Reason: `incompatible_evidence_type`; IDs: kronos.direction, research_view.why, kronos.model_id.
- risk attempt 2, `model_risks.0`: Model forecast direction is 'up' but research_view flags conflicting evidence and a primary risk that forecasts may not match market path.
  Reason: `incompatible_evidence_type`; IDs: kronos.direction, research_view.primary_risk, research_view.why.

Bull/Bear cite real synthetic bullish signals, but the deterministic direct-fact rule requires all non-stopword claim tokens to exist in cited string values. Wording such as labeled, snapshot, multiple, or indicators triggers rejection. This demonstrates a current wording/validator compatibility failure, not proof that the underlying bullish field was fabricated. Risk cites FORECAST plus RESEARCH_VIEW but declares one family, so the current compatibility rule rejects it. The last attempt and all prior failures remain auditable in claim_failure_inspection.json and attempt ledgers. No prompt or validator changes made.

## Checks and limitations
- Provider completion/truncation: PASS. The former900-token truncation concern did not recur with1600; valid end-to-end production recovery is NOT established.
- JSON parsing: PASS, all six reached CLAIM_VALIDATION. Initial shape/identity checks passed. Full structured contract/grounding/reference-family acceptance: FAIL. Full numerical and remaining-claim validation are NOT CONFIRMED because validation short-circuited; do not infer pass from no numerical exception.
- Evidence immutability, ledger, failed-output exclusion from success cache: PASS. No accepted reports, so success cache publication is not exercised.
- Durable retrieval: FAILED and2attempts per role survive reconstructed local Team.result/health, without Team.run or provider calls.
- Agent -> fusion: PASS for rejection isolation only. All agents remain explicitly missing; pre-agent fusion remains a cache hit with unchanged result hash. Successful-agent cache invalidation/integration NOT exercised. Fusion abstains with INSUFFICIENT_EVIDENCE; this fixture also lacks usable fusion-format technical/news/pipeline streams.
- Dashboard replay: PASS at1440,390,834 widths and reload, actual saved role failures, team Failed, pipeline FAILED, all rejected agents missing in fusion; no overflow, browser errors, POST requests, or external requests. Synthetic chart/news presentation fixture used only as UI context, not as a new live acquisition or API/auth route test. Screenshots and requests in live_confirmation_qa/.
- Observability: six attempts with run/snapshot/role/model/prompt/times/latency/usage/status/retry decisions plus three durable role ledgers. No hidden reasoning or secret contents retained.
- Production repair manifest hashes unchanged (19 files). Prior201passed/0failed/1skipped offline tests NOT rerun. Prior offline expert project score8.4/10 retained with explicit live gateRED; no full audit/rescore performed.

## Safety
OpenAI requests6, all within the single authorized workflow. Other external providers0. Kronos inference/training/weights0. Validation reruns0, locked targets0. Real NSE/Monad/user data transmittedNO. Transactions0. Production changes0. Commit/push0. Monad implementation not started.
Verification-only setup issues (privacy regex and installed httpx2 transport) occurred before the execution marker/provider attempts; fixed locally without production changes, dependency installs, or added provider calls.

## Next action
Perform one separate offline claim-contract compatibility repair for direct factual wording and mixed evidence-family declarations; no live retest without fresh authorization.
Stop: authorization is exhausted; no additional live call permitted.
