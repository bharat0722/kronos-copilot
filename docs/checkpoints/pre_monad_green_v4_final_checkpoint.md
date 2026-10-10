# Final Healthy Pre-Monad Kronos Foundation

Recorded: 2026-10-10 18:15:27 IST (2026-10-10T12:45:27Z).

## Repository Return Point

- Branch: `monad-metropolis`.
- Final checkpoint tag: `kronos-pre-monad-green-v4-final`.
- Source checkpoint: `e36fa8f3a6c30a89163e84f6ae331fd9a823501a`.
- Source tag: `kronos-phase8-pre-monad`, unchanged.
- Ancestry: source commit is an ancestor of this checkpoint. No history rewrite or merge into `main`.
- Resolve the final checkpoint commit with `git rev-parse kronos-pre-monad-green-v4-final^{commit}`. This document is introduced by that commit; its own hash is deliberately not embedded recursively.

This is the final healthy pre-Monad **software foundation**, not a claim of forecast accuracy. Monad implementation has not started. Canonical `main` remains at the separate Phase 8 return point. Phase 7, Audit #4 and Phase 8 remain complete; the fusion engine remains `evidence_fusion_v1`.

## Active Architecture

| Component | Version |
| --- | --- |
| Agent schema | `agent_output_v4` |
| Acceptance validator | `evidence_selection_validator_v2` |
| Role/use contract | `v4_role_use_contract_v2` |
| Bull prompt | `bull_agent_prompt_v10` |
| Bear prompt | `bear_agent_prompt_v9` |
| Risk prompt | `risk_agent_prompt_v9` |
| Production OpenAI model | `gpt-5-mini` |
| Maximum serialized input | 48,000 bytes |
| Maximum output | 1,600 tokens |
| Tools / reasoning rounds / retries | NONE / 1 / at most 1 per failed agent |

Earlier V2/V2.1/V3 designs let natural-language semantics participate in deterministic agent acceptance. Numerical paraphrases, units, direction wording, MIXED/uncertainty confusion, hedge keywords and FACT/DIRECT phrasing repeatedly caused rejection.

V4 changes the responsibility boundary:

- **Model:** select and rank admissible evidence IDs, with optional perspective/explanation.
- **Backend:** own facts, numbers, units, direction, conflicts, uncertainty, evidence families, role admissibility, grounding, provenance and final deterministic state.
- **Acceptance:** validate IDs, role/use pairs, actions, ranks, counts and snapshot/cache ownership. Unknown IDs, forbidden pairs and malformed structured results still fail.
- **Explanation:** non-authoritative and non-blocking. Unsafe or unusable optional prose is omitted and a deterministic fallback is rendered; it cannot fail an otherwise valid selection.
- **Fusion:** agent perspectives remain derived evidence with shared primary lineage and zero independent directional votes. Fusion weights were not tuned.
- **Abstention:** a valid completed outcome, not an execution failure.

Historical contracts and dated failure reports remain preserved, not reinterpreted under V4. Earlier V4 artifacts refer to validator v1; the final role/use repair and this checkpoint identify the active v2 contract.

## Final Scoped Health Gate

System, AI Research Team, Bull, Bear, Risk, Agent Harness, Evidence Fusion, Pipeline, Dashboard, Observability, Security and Architecture: **GREEN**. Architecture is green for a future Monad extension, not proof of forecasting skill.

Monad development readiness: **GREEN**. Permission for the subsequent research/architecture workstream: **YES**. Remaining scoped software blockers: **NONE**. No Monad research, implementation or transactions occurred during this checkpoint.

Evidence: [`final_pre_monad_health_gate.json`](../../research/results/healthcheck_postrepair/final_pre_monad_health_gate.json).

## Reliability Closure And Validation

Final reliability closure is **PARTIAL only for exact historical replay**: the rejected AXISBANK Window 2 Bull evidence ID/use/action payload was not retained. No reconstruction is claimed as recovered provider JSON.

The recorded failure was `role_admissibility` at `$.selected_evidence[0].use`. The former provider schema admitted independent ID and use enums, while backend rules admitted only particular pairs. The tightened nested schema and validator now consume the same role-admissibility source. Invalid bearish Bull SUPPORT still fails; valid COUNTER passes. No symbol whitelist, prose patch or V5 was introduced.

The failure class was reproduced offline. Corrected generic counter-evidence passed. Validator v2 invalidates earlier acceptance caches. One targeted **Bull-only live confirmation passed on its first attempt**. It was not a new full-team live run: its saved team is intentionally PARTIAL because Bear and Risk were not called.

- Latest full relevant offline baseline: **419 passed / 0 failed / 1 skipped**. Skip: explicitly opt-in live Yahoo regression.
- Current normal and adversarial full mocked V4 workflows: **3/3 each**.
- Prior V4 normal and adversarial live teams: **3/3 each**, seven provider requests total, no truncation; those historical results remain unchanged.
- Final scoped architecture assessment: **8.9/10**, not a measured model-performance score.
- Scoped gstack review/security and local desktop/iPad/phone QA passed. Combined gstack coverage remains PARTIAL because native Aside/Bun-dependent tooling was unavailable; this is disclosed, not presented as a full native review.
- Checkpoint verification matched all **13 frozen production Python source hashes** and **187 historical preservation hashes**. No material production change required a test rerun.
- Tests rerun during this checkpoint: **0**. OpenAI, Yahoo, Tavily, Kronos inference, training and scientific validation reruns: **0**.

Reports: [`final_role_admissibility_repair.md`](../../research/results/healthcheck_postrepair/final_role_admissibility_repair.md), [`v4_role_use_contract_v2.json`](../../research/results/healthcheck_postrepair/v4_role_use_contract_v2.json), [`axisbank_window2_bull_replay.json`](../../research/results/healthcheck_postrepair/axisbank_window2_bull_replay.json).

## Budget And Security Boundary

The obsolete custom daily 12-call project cap no longer gates production V4 execution or health. Durable daily usage accounting continues; historical V2/V3 replay retains its former behavior. No counters were reset.

Per-workflow bounds remain: full team at most six calls, Bull-only at most two, one retry per failed role, SDK retries zero. Provider/account limits, explicit authorization, input/output and cost/token guards, LAN access control, CSRF/origin protections, cache ownership and sanitized public errors remain active.

Credentials, local environments, model weights, runtime databases/caches, raw market dumps and temporary diagnostics are excluded. The checkpoint scan found no real credentials; deliberately synthetic security-test strings are not provider secrets.

## Real-World Findings: Preserved, Not Upgraded

**Test 1 - BAJFINANCE:** previously unused; full real market pipeline technically passed; V4 team 3/3; Fusion MIXED with LOW support and HIGH risk. News impact was truthfully degraded because substantive impact evidence was insufficient. A functioning system can still have limited research support.

**Test 2 - AXISBANK:** previously unused; three frozen blind 75-bar windows, no future-input leakage, news excluded for leakage prevention, all windows reported. Observed target coverage was 73/75, 73/75 and 72/75; no imputation. These were recent online challenge windows, not locked-test targets or a prospective strategy backtest.

| Preserved result | Value |
| --- | --- |
| Kronos direction hits | 1/3 |
| Beats Persistence by MAE | 0/3 |
| Beats Drift by MAE | 3/3 |
| Beats Momentum by MAE | 0/3 |
| Forecast performance | **WEAK IN THESE THREE WINDOWS** |

This is **not a general accuracy estimate**. The original black-box verdict remains PARTIAL, including Window 2 Bull failure and Window 3 obsolete-budget Risk block. Later software repair does not rewrite those original executions, forecasts, scores or verdicts. None of the windows was rerun or replaced to improve the result.

Reports: [`final_black_box_verdict.md`](../../research/results/final_real_world_challenge/final_black_box_verdict.md), [`test2_blind_reality.md`](../../research/results/final_real_world_challenge/test2_blind_reality.md), [`baseline_comparison.json`](../../research/results/final_real_world_challenge/baseline_comparison.json).

## Scientific Integrity And Separate Model Track

Locked-test targets were not opened or changed. Phase 1C/1D protected results, validation membership, benchmark definitions, weights and historical rejected V2/V3/V4 evidence were not rewritten. The checkpoint performs repository preservation, not scientific revalidation. Historical report hashes remain unchanged.

Weak blind performance belongs to **Phase 9 - Historical Evaluation** and the separate model-performance/fine-tuning track. It does not block Monad research/architecture. Fine-tuning remains waiting on trusted historical training data with provenance and stronger GPU / MU cloud support. No training or fine-tuning is authorized by this checkpoint.

## Included Changes And Local Exclusions

All intended changes are confined to validated agent/stabilization implementation, reliability repair, tests and portable fixtures, audit/health contracts and reports, real-world evaluation reports, these checkpoint documents and a concise README status update. No unexplained production change, deletion, unrelated file or Monad implementation is included.

The machine-readable companion records classifications and preservation hashes. Sanitized historical reports are explicitly staged despite the default results ignore rule. A narrowly scoped `.gitattributes` rule preserves both checkpoint report directories byte-for-byte, preventing Git line-ending conversion from changing historical evidence. Browser fixture blobs, transient failed-test logs, copy-verification/local manifests and screenshots remain local, alongside ignored runtime data and credentials; they are not substitutes for the committed final reports.

## Exact Next Roadmap Step

After this branch and tag are pushed and verified, **stop**. The next separately authorized task is:

Monad research -> track-fit audit -> onchain data research -> architecture design -> minimum hackathon adaptation plan -> implementation.

Keep canonical main and its Phase 8 checkpoint independent. Preserve Phase 9/model-performance and the waiting fine-tuning track separately. Returning to this foundation uses the branch, tag and commit above, with a clean or safely preserved worktree; no historical work must be repeated merely to recover it.
