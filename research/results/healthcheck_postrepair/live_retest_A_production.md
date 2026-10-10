# Final bounded live retest A

Status: FAIL.

Fixture: synthetic_production_v1_TESTCO. Snapshot: `b26ba306eb25260085510a6bea122b165c9c247dd6d53281bb8997ae3838f0f5`. Serialized bytes: 21420.

gpt-5-mini; Bullv7/Bearv6/Riskv6; agent_output_v2; cap1600; retry1; loop1; toolsNONE. Production input limit48000 unchanged.

Team: 0/3. Calls: 6. Usage: {"input_tokens": 63920, "output_tokens": 3627, "total_tokens": 67547}. API cost UNKNOWN for live requests.

| Role | Result | Attempts | Input tokens | Output tokens | Provider status | Failure |

|---|---|---:|---:|---:|---|---|

|bear|FAIL|2|20140|977|completed|CLAIM_VALIDATION|

|bull|FAIL|2|20140|1039|completed|CLAIM_VALIDATION|

|risk|FAIL|2|23640|1611|completed|NUMERICAL_GROUNDING|

All6Responsescompleted,450/589/459/518/819/792outputtokens, no truncation, no finish reason supplied. All failed outputs rejected before usable cache/publication.

Bull and Bear: unsupported_direct_fact, four attempts. Risk: field_or_unit_mismatch, two attempts. Numeric values exist in evidence but wording/unit context failed strict grounding; do not misreport all values as invented.

Successful team/grounding/integration gates FAIL or unconfirmed; durableFAILED, failureledger, cache rejection safety, unchanged evidence PASS.

Fusion correctly remains primary-only with all3missing-agent markers. Its operationalHEALTHY status is not a claim that agents succeeded. No pre-agent-cache invalidation is expected when all agents are rejected.

Desktop/390px phone/834px iPad intercepted saved-result QA PASS, reload remainsFAILED, correct per-role stage, no overflow/errors/private paths/secrets. Not an actual paid-route/LAN/current-market workflow.

Per-attempt sanitized provider metadata, exact claims/reasons/citations/usage and workflowmapping retained in JSON plus attempt_observability; no hidden reasoning/rawresponse/APIkeys.

Prior blocked reports archived byte-for-byte under archive/dual_live_retest_preflight_blocked_v1. No prompt/schema/validator/config/fixture/fusion changes during live run.

Safety: otherproviders0,inference/training/weights/Phase1C/1D/validation/lockedtargets/Monad/blockchain/commit/push0. Only authorized synthetic TESTCO sent. No extra diagnostic provider calls.

Highest-priority root cause: Live provider outputs still do not comply with exact typed grounding: FACT/DIRECT paraphrases and numeric field/unit wording are rejected. Do not repair within this validation task.
