# V3 Typed-Prose Repair and Diagnostic Hardening

## Verdict
PASS offline. Bull/Bear/Risk: GREEN OFFLINE. Team: YELLOW PENDING LIVE. Monad permission: NO.

## Root cause and call map
AgentTeam request -> Responses API output_text -> JSON parse -> validate_current_output -> v3.validate -> closed _shape -> typed notes/interpretations -> _prose -> fact references/stance -> durable attempt/run ledger -> cache/publish -> fusion/dashboard adapters.

The former v3 `_prose` required caution words even after the schema established INTERPRETATION / INTERPRETIVE. It also checked typed limitations and uncertainty. Ten retained attempts failed that rule, but their exact prose and field locations were discarded. This audit does not pretend to recover them. Historical v2/v2_1 validate_output and its interpretive-word heuristic are untouched.

## Narrow repair
V3 classification is structural. Keywords are optional, not evidence of truth. Schema remains `agent_output_v3`. Prompts remain Bull v9 / Bear v8 / Risk v8, with prompt hashes verified against retained live ledgers. Renderer unchanged. Acceptance validator: `evidence_native_grounding_v2`; prose validator: `typed_prose_validation_v1`. Cache identity already includes the acceptance validator, including fusion's agent adapter identity. Old accepted/rejected results are not silently reinterpreted.

Facts, values, units and directions remain backend-owned. Number-free prose, exact fact bindings, known citations, compatible families, role stances, bounds, explicit-fact/advice/injection guards remain enforced. Legitimate cross-family interpretation cites all sources. Bounded deterministic guards are not universal semantic entailment; qualitative support is not probability.

## Diagnostics
Failures retain rule, trusted JSON path, argument/type, cited IDs/families, reason, version, run/attempt/prompt and a sanitized excerpt of at most 240 characters. Schema failures now retain diagnostics too. Invalid JSON retains parser line/column but not raw payload. Malformed root responses are not excerpted. Environment secrets, keys, Bearer strings, private keys and filesystem paths are redacted. No hidden reasoning or full provider response is stored. Public errors remain generic and unchanged.

## Verification
Full offline suite: 335 passed / 0 failed / 1 skipped. Existing Yahoo live opt-in remains skipped. External connection/DNS blocking was active, with zero attempted external connections. Both native mocked production teams: 3/3 accepted, durable COMPLETE, validated caches/ledgers, input immutability, fusion lineage, no double counting, and adversarial conflicts retained.

Twelve structural replay cases: ten former keyword rejections become valid typed prose; one numerical and one representative schema violation remain rejected. Exact historical responses were not retained. All historical live reports/frozen fixtures and protected product/scientific modules remain byte-identical.

## Scoped gstack and architecture review
GSTACK: PARTIAL. Installed review/checklist (LLM trust, data safety, concurrency, enum consumers, exceptions, cache and test gaps) and CSO AI/security checklist applied to this change. Native Windows browse.exe was discovered and executed successfully; Bash preamble and Aside are unavailable; no setup download or outside-model call was made. Local Playwright browser QA: PASS (six cases). Native gstack browser QA: PASS (six cases), including desktop/phone/iPad and reload. Bash preamble and Aside remain unavailable. This is not a claim that the full native gstack workflows ran.

Custom scoped architecture assessment: 8.7/10. The responsibility boundary improves: typing determines classification, facts stay backend-owned, one shared validator serves all roles, legacy contracts are isolated and diagnostics are precise. Existing large harness ownership and universal semantic-entailment limits remain outside this repair.

## Fresh freeze and limits
Normal: 27091 bytes; adversarial: 27505 bytes. Maximum input 48000 bytes and output 1600 tokens unchanged. Loop 1 / retry 1 / tools NONE / daily cap 12 unchanged. Only three existing synthetic freshness timestamps were renewed; financial/news content and publication dates were not edited. Frozen fixture, wire, snapshot, prompt and source hashes are in v3_next_live_manifest.json. Future runs need fresh authorization, matching hashes, an unexpired one-hour freeze, empty live cache namespaces and sufficient persisted budget. Expiration requires an explicitly authorized timestamp-only refreeze, not silent edits.

## Safety and next action
OpenAI / Yahoo / Tavily / Monad / other external calls: 0. Inference/training/validation/locked-test access: 0. No commit, push or Monad work. Historical failed live evidence remains failed; offline success is not live confirmation.

Authorize another fresh normal + adversarial V3 live Agent Team confirmation. Do not execute without authorization.

## Final scoped review
Code and security checklist checks: PASS, no scoped blockers. Native gstack browser and Playwright each passed six cases with no overflow, console errors, secret/path display or external app requests. Browser runtime stopped and local QA server stopped after verification. No full outside-model review or full-repository security certification is implied.
