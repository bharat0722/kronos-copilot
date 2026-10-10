# Typed-Prose V3 Dual Live Confirmation
Status: FAIL
OpenAI calls: 12/12
Usage: {"input_tokens": 119610, "output_tokens": 10509, "total_tokens": 130119}
API cost: UNKNOWN; provider did not report monetary charges.
Test A: 0/3; Test B: 0/3.
Snapshot isolation: True; durable isolation: True; browser QA: PASS.
First-attempt pass rate: 0.0%; retry rate: 100.0%.
Output distribution: {"<=900": 9, "901-1200": 1, "1201-1599": 2, "TRUNCATED": 0, "UNKNOWN": 0}
Accepted mean: None; maximum: None.
Monad permission: False.

## Highest-priority remaining cause
{
  "rule_code": "unsupported_directional_conflict",
  "failure_category": "CLAIM_VALIDATION",
  "test": "A",
  "agent": "bear",
  "json_path": "$.arguments[0].stance",
  "excerpt": "MIXED",
  "reason": "unsupported directional conflict"
}

## Boundaries
Freshness-only change proof restores the new fixture byte-for-byte to the original after undoing exactly three timestamps and their deterministic snapshot IDs.
Task-specific persisted twelve-call allowance shared by both workflows; previous project usage not counted, production daily counters neither reset nor changed. Provider/account limits respected.
No contract changes during execution; no extra diagnostic calls, other providers, inference, training, validation, locked-test access, transactions, commits, pushes or Monad work.
335/0/1 is the latest offline suite; not rerun during this live task. Architecture score 8.7/10 is the prior scoped assessment, not a fresh full-project rating.
Hedge-free wording examples were verified offline; actual accepted hedge-free live arguments, where present, are retained in JSON. No claim of universal semantic entailment or investment accuracy.
## Next action
Address the single root cause above in a separate repair task; no repair performed here.
