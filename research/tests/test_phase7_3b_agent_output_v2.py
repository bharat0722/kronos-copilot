"""Offline closure tests for the typed Phase 7 agent_output_v2 contract."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import agent_research
from app.agent_research import (
    AGENTS,
    CLAIM_TYPES,
    EVIDENCE_TYPES,
    MAX_REASONING_ROUNDS,
    MAX_RETRIES,
    PROMPT_VERSIONS,
    SCHEMA_VERSION,
    SUPPORT_TYPES,
    AgentTeam,
    ClaimValidationError,
    NumericalGroundingError,
    evidence_catalog,
    output_schema,
    validate_output,
)
from app.evidence_snapshot import canonical_bytes, snapshot_id
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response
from research.tests.test_phase7_agents import evidence, snapshot, typed_claim, valid_report


RISK_FIELDS = ("risk_factors", "conflicts", "model_risks", "data_risks", "event_risks",
               "missing_evidence", "limitations", "uncertainty")


def set_material_claim(report: dict, agent: str, claim: dict) -> None:
    report["risk_factors" if agent == "risk" else "key_factors"] = [claim]
    if agent == "risk":
        report["evidence_ids"] = sorted({reference for field in RISK_FIELDS
                                         for item in report[field]
                                         for reference in item["evidence_ids"]})


class AgentOutputV2ClosureTests(unittest.TestCase):
    def setUp(self):
        self.record = snapshot(evidence())
        self.digest = self.record["snapshot_id"]
        self.catalog = evidence_catalog(self.record["evidence"])

    def validate(self, report: dict, agent: str) -> dict:
        return validate_output(report, agent, self.digest, self.catalog)

    def test_schema_exposes_required_claim_and_support_taxonomy(self):
        self.assertEqual(SCHEMA_VERSION, "agent_output_v2")
        self.assertEqual(set(CLAIM_TYPES), {"FACT", "NUMERICAL_FACT", "INTERPRETATION", "RISK",
                                            "LIMITATION", "UNCERTAINTY", "COMPARATIVE",
                                            "FORECAST_INTERPRETATION"})
        self.assertEqual(set(SUPPORT_TYPES), {"DIRECT", "DERIVED", "INTERPRETIVE", "MIXED", "INSUFFICIENT"})
        self.assertIn("MULTI_SOURCE", EVIDENCE_TYPES)
        properties = output_schema("bull", tuple(self.catalog))["properties"]["argument"]["properties"]
        self.assertEqual(set(properties), {"text", "claim_type", "support_type", "evidence_type",
                                           "evidence_ids", "confidence", "material"})

    def test_supported_and_unsupported_direct_qualitative_facts(self):
        supported = valid_report("bull", self.digest)
        set_material_claim(supported, "bull", typed_claim("Kronos direction is up.", ["kronos.direction"],
                                                           claim_type="FACT", support_type="DIRECT"))
        self.assertEqual(self.validate(supported, "bull"), supported)

        unsupported = valid_report("bull", self.digest)
        set_material_claim(unsupported, "bull", typed_claim("The company announced a new partnership.",
                                                             ["technicals.indicator.0"], claim_type="FACT",
                                                             support_type="DIRECT", evidence_type="TECHNICAL"))
        with self.assertRaisesRegex(ClaimValidationError, "not present"):
            self.validate(unsupported, "bull")

    def test_supported_and_unsupported_numerical_facts(self):
        supported = valid_report("bull", self.digest)
        set_material_claim(supported, "bull", typed_claim("The forecast change is 1.2%.",
                                                           ["kronos.forecast_pct_change"],
                                                           claim_type="NUMERICAL_FACT", support_type="DIRECT"))
        self.assertEqual(self.validate(supported, "bull"), supported)
        unsupported = copy.deepcopy(supported)
        unsupported["key_factors"][0]["text"] = "The forecast change is 15%."
        with self.assertRaises(NumericalGroundingError):
            self.validate(unsupported, "bull")

    def test_interpretation_requires_evidence_and_cannot_be_mislabeled_fact(self):
        supported = valid_report("bear", self.digest)
        set_material_claim(supported, "bear", typed_claim(
            "The neutral research view may limit downside conviction.", ["research_view.direction"],
            evidence_type="RESEARCH_VIEW"))
        self.assertEqual(self.validate(supported, "bear"), supported)

        mislabeled = copy.deepcopy(supported)
        mislabeled["key_factors"][0].update(claim_type="FACT", support_type="DIRECT")
        with self.assertRaisesRegex(ClaimValidationError, "FACT"):
            self.validate(mislabeled, "bear")

    def test_risk_limitation_and_uncertainty_require_lineage(self):
        risk = valid_report("risk", self.digest)
        self.assertEqual(self.validate(risk, "risk"), risk)
        for field in ("risk_factors", "limitations", "uncertainty"):
            with self.subTest(field=field):
                invalid = valid_report("risk", self.digest)
                invalid[field][0]["evidence_ids"] = []
                with self.assertRaisesRegex(ClaimValidationError, "lineage"):
                    self.validate(invalid, "risk")

    def test_incompatible_and_nonexistent_evidence_are_rejected(self):
        incompatible = valid_report("bull", self.digest)
        set_material_claim(incompatible, "bull", typed_claim("The technical signal may support the case.",
                                                              ["technicals.indicator.0"],
                                                              evidence_type="NEWS"))
        with self.assertRaisesRegex(ClaimValidationError, "incompatible"):
            self.validate(incompatible, "bull")
        missing = valid_report("bull", self.digest)
        set_material_claim(missing, "bull", typed_claim("The article may support the case.",
                                                         ["news.article.999"], evidence_type="NEWS"))
        with self.assertRaisesRegex(ClaimValidationError, "Unknown"):
            self.validate(missing, "bull")

    def test_field_aware_rsi_and_forecast_validation_is_symmetric(self):
        cases = (("RSI is 55.", "technicals.indicator.0", "TECHNICAL", "RSI is 62."),
                 ("The forecast change is 1.2%.", "kronos.forecast_pct_change", "FORECAST",
                  "The forecast change is 15%."))
        for agent in AGENTS:
            for supported_text, reference, evidence_type, unsupported_text in cases:
                with self.subTest(agent=agent, field=reference):
                    report = valid_report(agent, self.digest)
                    claim = typed_claim(supported_text, [reference], claim_type="NUMERICAL_FACT",
                                        support_type="DIRECT", evidence_type=evidence_type)
                    set_material_claim(report, agent, claim)
                    self.assertEqual(self.validate(report, agent), report)
                    report = copy.deepcopy(report)
                    report["risk_factors" if agent == "risk" else "key_factors"][0]["text"] = unsupported_text
                    with self.assertRaises(NumericalGroundingError):
                        self.validate(report, agent)

    def test_price_and_volume_validation_is_symmetric(self):
        content = copy.deepcopy(self.record["evidence"])
        content["market_data"].update(last_observed_close=100, currency="INR", volume=1000)
        record = snapshot(content)
        catalog = evidence_catalog(content)
        cases = (("Price is ₹100.", ["market_data.last_observed_close", "market_data.currency"], "Price is ₹120."),
                 ("Volume is 1000.", ["market_data.volume"], "Volume is 1200."))
        for agent in AGENTS:
            for supported_text, references, unsupported_text in cases:
                with self.subTest(agent=agent, text=supported_text):
                    report = valid_report(agent, record["snapshot_id"])
                    claim = typed_claim(supported_text, references, claim_type="NUMERICAL_FACT",
                                        support_type="DIRECT", evidence_type="MARKET_DATA")
                    set_material_claim(report, agent, claim)
                    self.assertEqual(validate_output(report, agent, record["snapshot_id"], catalog), report)
                    report = copy.deepcopy(report)
                    report["risk_factors" if agent == "risk" else "key_factors"][0]["text"] = unsupported_text
                    with self.assertRaises(NumericalGroundingError):
                        validate_output(report, agent, record["snapshot_id"], catalog)

    def test_same_number_from_wrong_field_fails_for_every_role(self):
        content = copy.deepcopy(self.record["evidence"])
        content["news"]["article_evidence"][0]["relevance"] = 55
        record = snapshot(content)
        catalog = evidence_catalog(content)
        for agent in AGENTS:
            report = valid_report(agent, record["snapshot_id"])
            claim = typed_claim("RSI is 55.", ["news.article.0"], claim_type="NUMERICAL_FACT",
                                support_type="DIRECT", evidence_type="NEWS")
            set_material_claim(report, agent, claim)
            with self.subTest(agent=agent), self.assertRaises(NumericalGroundingError):
                validate_output(report, agent, record["snapshot_id"], catalog)

    def test_v1_cache_identity_is_not_reused(self):
        team = AgentTeam(Path("unused"))
        current = team._key(self.digest, "bull")
        with patch.object(agent_research, "SCHEMA_VERSION", "agent_output_v1"):
            old = team._key(self.digest, "bull")
        self.assertNotEqual(current, old)

    def test_rejected_claim_is_not_cached_and_has_sanitized_diagnostic(self):
        def rejected(name):
            report = valid_report(name, self.digest)
            if name == "bull":
                set_material_claim(report, name, typed_claim("A partnership was announced.",
                                                             ["technicals.indicator.0"], claim_type="FACT",
                                                             support_type="DIRECT", evidence_type="TECHNICAL"))
            return mock_response(name, self.digest, report=report)

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: MockClient(rejected)).run_bull_only(self.record)
            attempts = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "attempts").glob("*.json")]
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(list((root / "cache").glob("*.json")) if (root / "cache").exists() else [], [])
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(row["failure_stage"] == "CLAIM_VALIDATION" and
                            row["validation_diagnostic"]["failure_reason"] == "unsupported_direct_fact"
                            for row in attempts))

    def test_ledger_stores_typed_claim_metadata_and_team_preserves_lineage(self):
        client = MockClient(lambda name: mock_response(name, self.digest))
        original = canonical_bytes(self.record)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run(self.record)
            rows = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "runs").glob("*.json")]
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(canonical_bytes(self.record), original)
        self.assertEqual(set(result["agents"]), set(AGENTS))
        self.assertNotIn("synthesis", result)
        self.assertTrue(all(row["output_schema_version"] == "agent_output_v2" and
                            row["claim_validation"]["status"] == "PASS" and row["claim_metadata"]
                            for row in rows))
        for row in rows:
            self.assertEqual(set(row["evidence_references"]),
                             {reference for claim in row["claim_metadata"]
                              for reference in claim["evidence_ids"]})

    def test_tools_loops_retries_and_prompt_versions_remain_bounded(self):
        team = AgentTeam(Path("unused"))
        wire = canonical_bytes({"evidence": self.record["evidence"]})
        for agent in AGENTS:
            request = team._request_args(agent, wire)
            self.assertEqual(request["tools"], [])
            self.assertEqual(request["tool_choice"], "none")
            self.assertFalse(request["parallel_tool_calls"])
        self.assertEqual(MAX_REASONING_ROUNDS, 1)
        self.assertEqual(MAX_RETRIES, 1)
        self.assertEqual(PROMPT_VERSIONS, {"bull": "bull_agent_prompt_v5",
                                           "bear": "bear_agent_prompt_v4",
                                           "risk": "risk_agent_prompt_v4"})


if __name__ == "__main__":
    unittest.main()
