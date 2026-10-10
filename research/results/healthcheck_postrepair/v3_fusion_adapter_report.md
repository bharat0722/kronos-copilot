# V3 Fusion and Dashboard Adapter Review

## Contracts

Production v3 reports carry selected canonical fact references and separately typed
interpretations. Backend presentation resolves facts from the same immutable snapshot.
The fusion projection is a compatibility view, not another source of factual truth.
No extra LLM, provider, indicator or inference is introduced.

Bull, Bear and Risk remain DERIVED with contributes_to_direction=false. Primary
forecast/technical/news evidence is not counted again. Risk affects existing support
and warnings, not an independent financial direction vote. LOW/MEDIUM/HIGH support
maps to an explicitly ordinal .25/.5/.75 compatibility scale, with INSUFFICIENT=0;
these are not statistical probabilities or new tuned weights.

Fact-reference pairs, interpretation IDs, individual agent run ID, current snapshot,
schema and cached state survive. Risk's new argument list is projected into the
existing risk list. A failed v3 validator, unknown schema or wrong snapshot excludes
that role from both evidence items and Risk influence. This closes an adjacent
otherwise-unvalidated side path without changing evidence_fusion_v1 financial rules.

V3 adapter version joins v3 fusion cache identity. Historical no-v3 cache identity
does not receive the new field. Upstream inputs are byte-equal before/after fusion.

## Native Offline Proofs

Both normal and adversarial production-shaped fixtures pass all three mocked roles,
durable reload, accepted cache, parent/attempt ledger, pipeline count, fact rendering,
fusion refresh, lineage and immutability. The adversarial primary conflict remains
visible. Agent-derived interpretation cannot resolve it by silently averaging or
duplicating upstream votes. Details: v3_offline_A.json and v3_offline_B.json.

The existing cards use backend presentation only for v3; historical card behavior
remains available for historical display. Facts use textContent, interpretation is
labeled, and qualitative support never appears as prediction probability. Scoped
browser QA covers both cases at 1440, 390 and 834px, initial display and reload,
pipeline 3/3, snapshot association, no horizontal overflow, no errors and no secret/
path disclosure. All requests are intercepted; no privileged POST or external request
occurs. Screenshots are under v3_qa/. This does not validate live market/chart/news
alignment, live authentication sessions or real provider compliance.

## Gate

Offline adapter gate: PASS. Real-provider v3 gate: NOT RUN. Agent Team remains
YELLOW PENDING LIVE V3; Monad permission remains NO. Existing failed-live reports
and prior readiness history are not rewritten as successes.
