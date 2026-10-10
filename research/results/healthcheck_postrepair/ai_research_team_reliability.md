# AI Research Team reliability

Offline: PASS. Actual provider: UNCONFIRMED. Live confirmation needed: YES. Team/Bull/Bear/Risk remain YELLOW until the bounded provider test; harness/cache/ledger are GREEN within offline scope.

Root cause from unchanged old audit: all latest six SDK attempts returned incomplete/max_output_tokens at900, 0/3 accepted; matching September30 run54.03s. No new provider attempt was made here.

Implemented: 1600 ceiling without escalation, short typed claims/mandatory caveats, versioned prompts, strict schema and deterministic fit preflight. agent_output_v2 and numerical/qualitative/reference grounding remain intact. Normal600-900 is a target; mock byte/4 approximation: {"bull": {"json_bytes": 1062, "token_approximation": 266}, "bear": {"json_bytes": 1062, "token_approximation": 266}, "risk": {"json_bytes": 1385, "token_approximation": 346}}. Production input bytes: 41477; >=60 populated catalog entries. Mock success does not show actual model token usage or eliminate provider-managed reasoning cost.

Verified: local HTTP full team3/3; successful ledger before cache; COMPLETE/PARTIAL/FAILED restart; old failure recovery; new same-symbol snapshot READY instead of stale COMPLETE; age/current identity rejection before any SDK call; evidence changes between roles stop later calls; concurrency/cancellation; state persistence failure fails before call. Forced repeated truncations produce6 attempt rows, exactly one retry/role, cap1600 on both, OUTPUT_TRUNCATED/providerreason/usage retained, no invalid success cache. Accepted partial agents refresh fusion, missing Risk remains visible.

See bounded_live_confirmation_spec.json. No live run authorized or executed. Stop after fresh authorization for one bounded synthetic team; no automatic prompt tuning or repeated searches.
