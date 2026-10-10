# V3 Dual Live Confirmation

Status: FAIL
OpenAI calls: 12 / 12
Token usage: {"input_tokens": 119628, "output_tokens": 11727, "total_tokens": 131355}
API cost: UNKNOWN (not reported by provider)
Test A: FAIL
Test B: FAIL
Snapshot isolation: True
Durable isolation: True
Browser QA: PASS
Monad permission: False

## Budget and Privacy
Task-scoped persistent budget shared by both workflows. Production daily counters not reset or changed.
Only synthetic NSE:TESTCO snapshots transmitted to official OpenAI Responses endpoint. No other external service used.
Only required snapshot/acquisition/technical freshness metadata changed; original news publication dates preserved.

## Efficiency
V3 accepted mean output: None
V3 accepted maximum output: None
V3 retry-role rate: 1.0
Previous v2_1 output summary: {"attempts": 12, "mean_output_tokens": 846.5833333333334, "max_output_tokens": 1230, "note": "Descriptive two-fixture comparison only, not a reliability estimate or statistically controlled token benchmark."}
Schema responsibility is reduced, not necessarily total tokens. Do not generalize reliability from two runs.

## Observed Rejections
Counts: {"unlabelled_interpretation": 10, "Agent v3 schema validation failed": 1, "model_generated_number": 1}
Highest-priority remaining cause: The shared v3 _prose guard rejects typed prose without a required caution keyword (unlabelled_interpretation); ten of twelve attempts fail this rule. The guard applies to interpretations, limitations and uncertainty notes; the exact failing text/location was not retained.
The exact failing prose and the schema failure subcode are unavailable in retained diagnostics; no facts about discarded response text are invented.
One attempt triggered model_generated_number. This identifies a rejected attempt, not the exact count of numerical spans. Published unsupported numbers: zero.
Accepted fact rendering, claim traceability and agent-to-fusion integration remain unproven live because neither team produced an accepted result.
Fusion retained all missing-agent markers and Test B primary conflicts. Failure state and absence of success cache survived reload.
## Boundary
Existing functional offline suite was not rerun. No scientific evaluation or target read occurred.
Architecture score remains the scoped 8.6/10 assessment, not a new full-project score.
