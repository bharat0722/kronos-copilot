# Final bounded live retest B

Status: BLOCKED.

Fixture: synthetic_adversarial_v1_TESTCO. Snapshot: `f4a93fb9f8bd5268693700832d23610fb1e38e6787a7604e75bccc33963bc7a4`. Serialized bytes: 21834.

gpt-5-mini; Bullv7/Bearv6/Riskv6; agent_output_v2; cap1600; retry1; loop1; toolsNONE. Production input limit48000 unchanged.

Team: 0/3. Calls: 0. Usage: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}. API cost UNKNOWN for live requests.

| Role | Result | Attempts | Input tokens | Output tokens | Provider status | Failure |

|---|---|---:|---:|---:|---|---|

|bull|NOT RUN|0|0|0|NOT RUN|NOT RUN|

|bear|NOT RUN|0|0|0|NOT RUN|NOT RUN|

|risk|NOT RUN|0|0|0|NOT RUN|NOT RUN|

Test A used6calls on top of6earlier daily calls; production daily cap12 exhausted. No budget reset or bypass.

File/wire hashes,size,freshness,configuration and normal cachemissPASS. Combined preflightFAIL on cost guard. All provider/claim/fusion integration tests NOT RUN, not PASS.

No TestBworkflow started and no TestBprovider attempts exist. TestAsnapshot/caches were never attributed toTestB.

Prior blocked reports archived byte-for-byte under archive/dual_live_retest_preflight_blocked_v1. No prompt/schema/validator/config/fixture/fusion changes during live run.

Safety: otherproviders0,inference/training/weights/Phase1C/1D/validation/lockedtargets/Monad/blockchain/commit/push0. Only authorized synthetic TESTCO sent. No extra diagnostic provider calls.

Highest-priority root cause: Live provider outputs still do not comply with exact typed grounding: FACT/DIRECT paraphrases and numeric field/unit wording are rejected. Do not repair within this validation task.
