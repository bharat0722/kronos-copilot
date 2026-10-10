# Architecture recheck

Custom architecture: 7.5 -> **8.0/10**, GREEN for safe extension of locally tested boundaries. Overall development gate still YELLOW/NO pending actual provider confirmation. This is not the gstack composite score.

Dashboard -> authenticated DashboardHandler -> current_paid_agent_snapshot -> bounded AgentTeam -> strict typed/grounding validators -> durable attempts/role ledger -> validated cache -> canonical team state -> deterministic aggregator -> fusion -> health/UI.

AgentTeam now owns durable snapshot-specific state; server/UI consume it rather than infer readiness from cache alone. Current pointer/fingerprint/source age checked before paid attempts; forecast read joins use existing reentrant lock. Provider seam/caches unchanged. Fusion cache includes agent report identity, so accepted roles invalidate pre-agent outputs. Fusion algorithm/rules/weights unchanged; only health presentation/expiry changed.

New tests use tracked synthetic fixture or deterministic in-test generation, not ignored private caches. Error sanitization is central, and whole-chain news health is separate from Tavily health. Unknown fallback latency is null. Fusion health tied to current snapshot. Research maturity/completeness stays visible separately from operational outcomes.

Server remains a large join/routing module and agent work remains synchronous per request: ACCEPTED NON-BLOCKER L2, not repaired by a risky decomposition. Browser timeout210s is not server cancellation; cancellation event stops subsequent attempts, not an already in-flight SDK request. Socket server threads keep status endpoints available. Filesystem failure fails closed, though it can prevent a durable failure record.

gstack1.91.2.0: review/cso/qa-only offline-adapted checklists; health test dimension10 only. Native telemetry/browser setup/outside reviewer and full type/lint/dead-code/supply-chain scans were not run. No new abstraction/provider/agent/indicator or Monad implementation added. No numerical forecasting accuracy claim.
