# Pre-Monad foundation remediation

Status: **PARTIAL**. Offline remediation: PASS. Monad gate: **YELLOW / NO**.
Original 900-token failure: **NOT FIXED in the actual-provider proof sense**. Code mitigation and offline proof pass; a fresh authorized live confirmation is required.

## Health comparison
Same risk-weighted expert rubric as the original audit: AI team x3, pipeline and observability x2, other areas x1. Before 7.2/10; after 8.4/10. Scores are engineering judgments, not forecasting accuracy. A score cannot override the pending live gate.

| Area | Before | After |
|---|---|---|
| Repository integrity | GREEN 9 | GREEN 9 |
| Environment | YELLOW 8 | GREEN 8.5 |
| Server/API | YELLOW 7 | GREEN 8.5 |
| Market data | GREEN 8.5 | GREEN 8.5 |
| Bronze/Silver/Gold | YELLOW 8 | GREEN 8.5 |
| Kronos wrapper | YELLOW 7.5 | GREEN 8 |
| Technicals | GREEN 9 | GREEN 9 |
| News | GREEN 8.5 | GREEN 8.5 |
| Evidence snapshot | YELLOW 7.5 | GREEN 8.5 |
| AI Research Team | RED 4 | YELLOW 7 |
| Evidence Fusion | GREEN 8.5 | GREEN 8.5 |
| Pipeline health | YELLOW 5.5 | GREEN 8.5 |
| Dashboard | YELLOW 7 | GREEN 8.5 |
| Auth/security | YELLOW 8.5 | GREEN 9 |
| Caching | GREEN 8.5 | GREEN 8.5 |
| Ledger | GREEN 9 | GREEN 9 |
| Observability | RED 5 | GREEN 8.5 |
| Scientific integrity | GREEN 10 | GREEN 10 |
| Test coverage | YELLOW 7 | GREEN 9 |
| Architecture | YELLOW 7.5 | GREEN 8 |

## Findings
- **H1 OPEN BLOCKER**: Response headroom 1600, concise typed claims, budget preflight and OUTPUT_TRUNCATED diagnostics implemented; actual provider recovery is unconfirmed.
- **M1 RESOLVED**: Durable snapshot-specific canonical team state; individual failures, partial and complete survive restart; UI and health consume the same state.
- **M2 RESOLVED**: Tracked synthetic fixture replaces ignored smoke-spec dependency; instrument names mocked; production-sized payload and real local HTTP integration added.
- **M3 RESOLVED**: Paid execution verifies current canonical pointer, content/forecast ownership and <=3600s snapshot/source age before each SDK attempt; historical result reads remain available.
- **M4 RESOLVED**: Operational success is separate from research status/completeness. Old DEGRADED stages age to STALE; whole-chain news and snapshot-scoped fusion health are truthful. Unknown fallback latency is null.
- **M5 RESOLVED**: Non-domain exceptions receive generic public messages; trusted AgentError contracts remain structured. Synthetic path-bearing handler errors do not expose paths.
- **L1 RESOLVED**: Saved ticker initializes request controls; pending 120-bar request is clearly distinguished from unchanged saved 75-bar result.
- **L2 ACCEPTED NON-BLOCKER**: Heavy imports and synchronous per-request work remain. Browser timeout is bounded, active state is visible, and other server threads remain available. No broad performance refactor.

## Validation
201 passed / 0 failed / 1 skipped (202 total). Existing opt-in live Yahoo test skipped. External attempts/calls zero. The previous checkpoint's historical test count is not rewritten.
Production-like local HTTP request -> fresh evidence -> mocked Bull/Bear/Risk -> typed validation -> durable ledger -> cache -> COMPLETE -> fusion -> pipeline passes, 3/3. Six forced truncations stay at 1600 with one retry per role, durable diagnostics and no usable success cache.
Browser QA: 1440px desktop, 390px phone, 834px iPad, synthetic APIs only. Failed reload, partial Risk, complete/fusion update, stale disablement, auth modal, double-click guard, saved ticker and pending horizon all pass. Eight nonblank chart canvases; no overflow, unexpected console errors or external requests. This is not a physical-iPad or real-provider test.
An intermediate added assertion used an invalid synthetic digest; corrected to a valid content hash and the full suite passed. No failed run is represented as the final validation.

## Policies
gpt-5-mini; Bullv6/Bearv5/Riskv5; agent_output_v2; 1600 hard output cap; target 600-900 (design target, not measured live usage). Bull/Bear <=3 typed claims total; Risk <=4; required limitations/uncertainty retained. Claim text <=240 characters. No tools, loop1, retry1, SDK retries0, daily12, input48000, timeout30s. Team worst case6 calls/9600 output tokens. Daily theoretical output ceiling19200; cost not estimated.
Snapshot eligibility requires current identity and snapshot/source age <=3600s before each paid attempt. Historical cached/failure displays remain possible, with eligible false when expired. Browser timeout210s does not cancel an in-flight provider request; saved RUNNING state remains honest.

## Review and safety
Installed gstack1.91.2.0 review/security/health/QA checklists applied in offline-adapted mode. Native telemetry/Aside/outside-model review not run. Test-tool score10 applies only to executed-test dimension; holistic gstack score unavailable. Custom architecture7.5 ->8.0, independent of gstack rubric. Full type/lint/dead-code/vulnerability scans unavailable, not fabricated passes.
Fusion AST equality excluding health() verified: rules, weights, normalized evidence and output identities unchanged. No forecast mathematics or scientific artifacts changed. Source/checkpoint branch remains monad-metropolis; no commit/push.
External APIs/LLMs/Tavily/Yahoo, Kronos inference/training, weights, validation and locked-test target accesses: zero. No Monad or Phase9 implementation.

## Limitations and decision
Actual provider completion/typical token usage not proven. Existing server needs restart to load copied code. CPU-only fine-tuning constraints remain outside this product health gate. Fundamentals and historical fusion calibration remain honest research limitations, not broken pipeline states.
**Next action:** Obtain fresh authorization for exactly one synthetic production-like three-agent live smoke test.
