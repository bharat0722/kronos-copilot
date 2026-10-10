# Final V4 Role-Admissibility Reliability Repair

Closure: PARTIAL for the requested exact historical replay; software reliability: PASS.
System health and Monad architecture/research readiness: GREEN. No Monad work, commit or push performed.

## Proven Root Cause
Classification: OTHER - provider schema / validator pairing mismatch.
The previous provider schema independently allowed all catalogue IDs and all SUPPORT/COUNTER/RISK enums.
The unchanged backend catalogue admitted only particular ID/use pairs. Thus strict JSON could still contain a forbidden pair.
The original two attempts failed role_admissibility at $.selected_evidence[0].use.
Their exact evidence ID, requested use and action were not retained. No reconstructed pair is presented as recovered provider JSON.

## Repair
V4 responsibility boundary, schema name, role rules, facts, numbers, units and prose non-blocking behavior remain unchanged.
Acceptance identity: evidence_selection_validator_v2; role-use contract: v4_role_use_contract_v2.
Nested anyOf schema branches are generated from the same catalogue admissibility as the validator; IDs cannot be paired with forbidden uses.
Snapshot enum and selection limits are constrained at the provider boundary. Unknown IDs/use enums remain invalid.
Bull bearish SUPPORT and Bear bullish SUPPORT still fail. Opposing COUNTER evidence and valid ABSTAIN remain successful outcomes.
Counter-only cases retain INSUFFICIENT support; they are not relabeled bullish or treated as forecasting success.
Rejected selection diagnostics now retain bounded sanitized ID, requested/allowed uses, role compatibility, family, direction, action and field path.
No provider prose, hidden reasoning, keys or private payload are persisted in those diagnostics.
Prompt content hashes and versions are unchanged. Validator identity changes invalidate prior acceptance cache keys.
[OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs) supports nested anyOf and bounded arrays for the configured base model.

## Budget Policy
The obsolete daily 12-call project limit no longer governs production V4 execution or health.
Durable daily accounting continues. Public team workflows allow at most six calls; Bull-only allows at most two; one retry per role, SDK retries zero.
Historical V2/V3 replay retains its former daily behavior. Tavily budgets, account/provider limits, auth, CSRF/origin, input/output guards remain unchanged.
The actual shared daily count was 12 before the authorized Bull run and 13 afterward; no counter reset or deletion.

## Offline And Live Proof
Full relevant suite: 419 passed / 0 failed / 1 skipped; no outbound network attempts.
Normal and adversarial full mocked V4 workflows: 3/3 each. Cache, ledger, durability, fusion, lineage, conflicts, pipeline and dashboard checks passed.
Six report-only desktop/iPad/phone browser cases passed with reload, nonblank chart, no overflow, no console errors or private-content leaks.
Critical original structural equivalent: bearish Kronos direction used as Bull SUPPORT fails at the historical rule/path; corrected COUNTER passes.
This reproduces the failure CLASS, not the missing original response.
Exactly one Bull-only real-provider workflow ran and passed on its first call. No Bear, Risk, news, market-data fetch or inference rerun.
A timestamp-only copy retained identical forecast, technical, news, numerical, risk and role catalogue content. Source-bar timestamp stays historical.
Fresh snapshot: 3fbe55a295384d061e4846d7c16f9aa5eb440e602d886cc8b92a91aec68cff1f. Input: 11,938 bytes. Provider response completed, no truncation.
Usage: {'input_tokens': 3909, 'output_tokens': 237, 'total_tokens': 4146}; monetary API cost UNKNOWN.
Bull selected technical trend and forecast direction as COUNTER, plus missing-news context as RISK.
Backend direction remained BEARISH, support INSUFFICIENT, with MISSING_NEWS and NO_ROLE_ALIGNED_SUPPORT.
Saved retrieval and local fusion refresh passed. The Bull-only live team is deliberately PARTIAL because other roles were not run.

## Review And Architecture
Scoped gstack review/security checklists and local browser QA: PASS. Combined gstack status: PARTIAL; native Aside unavailable and native learning log lacks Bun. No extra independent LLM judge calls.
No blocking scoped review findings. Architecture GREEN; 8.9/10 scoped engineering assessment.
V4 still validates boring structured selections; no V3 prose semantics or role-specific whitelist was introduced.

## Scientific Preservation
187 pre-existing report, snapshot, forecast, score, ledger and unchanged production-file hashes verified.
Historical AXISBANK windows and black-box artifacts are byte-for-byte unchanged.
Blind forecast performance remains WEAK: direction 1/3; MAE wins versus Persistence 0/3, Drift 3/3, Momentum 0/3.
No inference, training, model weights, fusion weights, technical thresholds, locked-test targets or scientific benchmark runs changed.
Software reliability closure does not improve or erase this predictive-performance evidence; Phase 9 / the separate model track must address it.

## Final Decision
Remaining software blockers: none within this scoped gate. Exact historical rejected-output reconstruction remains unavailable, not fabricated.
Monad architecture/research permission: YES. Implementation not started.
Checkpoint and push the healthy pre-Monad foundation. Preserve the weak blind-performance result as Phase 9 evidence. Then begin Monad research, audit and architecture.
