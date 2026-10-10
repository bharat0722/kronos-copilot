"""Historical v2_1 replay ONLY. Never imported by application/runtime code.

Keeps old contract regression inputs intact while current production execution
and all native v3 tests use AgentTeam without these overrides.
"""
import json
from app import agent_research as ar


class LegacyAgentTeam(ar.AgentTeam):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, contract_version='agent_output_v3', **kwargs)
    def _serialize_input(self, record):
        return ar.canonical_bytes({'snapshot_id': record['snapshot_id'], 'evidence': record['evidence'],
                                   'evidence_catalog': ar.evidence_catalog(record['evidence'])})

    def _ledger(self, row):
        row['output_schema_version'] = 'agent_output_v2_1'
        super()._ledger(row)

    def _attempt_ledger(self, row):
        row['schema_version'] = 'agent_attempt_v3'
        row['output_schema_version'] = 'agent_output_v2_1'
        super()._attempt_ledger(row)

    def _validate_report(self, report, agent_type, digest, catalog, **kwargs):
        return ar.validate_output(report, agent_type, digest, catalog)

    def _presentation(self, report, catalog):
        return None

    def _request_args(self, agent_type, evidence_bytes):
        request = super()._request_args(agent_type, evidence_bytes)
        ids = ar.allowed_evidence_ids(ar.evidence_catalog(json.loads(evidence_bytes)["evidence"]))
        request["instructions"] = ar.legacy_instructions(agent_type)
        request["text"]["format"]["name"] = f"{agent_type}_agent_report_v2_1"
        request["text"]["format"]["schema"] = ar.output_schema(agent_type, ids)
        return request


class LegacyV3AgentTeam(ar.AgentTeam):
    """Explicit frozen v3 behavior; never used by the production server."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, contract_version='agent_output_v3', **kwargs)
