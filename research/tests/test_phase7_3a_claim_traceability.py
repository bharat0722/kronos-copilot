"""Offline characterization tests for the Phase 7.3A qualitative-grounding audit."""

from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam

import copy
import unittest

from app.agent_research import (
    ClaimValidationError,
    NumericalGroundingError,
    allowed_evidence_ids,
    evidence_catalog,
    output_schema,
    validate_output,
)
from research.tests.test_phase7_agents import evidence, snapshot, typed_claim, structured_fact, valid_report


class Phase73AClaimTraceabilityTests(unittest.TestCase):
    def setUp(self):
        self.record = snapshot(evidence())
        self.catalog = evidence_catalog(self.record["evidence"])
        self.digest = self.record["snapshot_id"]

    def test_direct_supported_qualitative_fact_passes(self):
        report = valid_report("bull", self.digest)
        report["key_factors"] = [structured_fact("forecast_direction", "up", "state", ["kronos.direction"])]
        self.assertEqual(validate_output(report, "bull", self.digest, self.catalog), report)

    def test_irrelevant_direct_qualitative_citation_is_rejected(self):
        report = valid_report("bull", self.digest)
        report["key_factors"] = [typed_claim("The company announced a new partnership.",
                                             ["technicals.indicator.0"], claim_type="FACT",
                                             support_type="DIRECT", evidence_type="TECHNICAL")]
        with self.assertRaises(ClaimValidationError):
            validate_output(report, "bull", self.digest, self.catalog)

    def test_supported_numerical_fact_passes(self):
        report = valid_report("bull", self.digest)
        report["key_factors"] = [structured_fact("forecast_return_pct", 1.2, "percent", ["kronos.forecast_pct_change"])]
        self.assertEqual(validate_output(report, "bull", self.digest, self.catalog), report)

    def test_unsupported_number_is_rejected(self):
        report = valid_report("bull", self.digest)
        report["key_factors"] = [typed_claim("The forecast change is 15%.",
                                             ["kronos.forecast_pct_change"],
                                             claim_type="NUMERICAL_FACT", support_type="DIRECT")]
        with self.assertRaises(NumericalGroundingError):
            validate_output(report, "bull", self.digest, self.catalog)

    def test_interpretive_bull_bear_and_risk_claims_with_citations_pass(self):
        bull = valid_report("bull", self.digest)
        bull["key_factors"] = [typed_claim("The forecast may support a constructive interpretation.",
                                           ["kronos.direction"], claim_type="FORECAST_INTERPRETATION")]
        bear = valid_report("bear", self.digest)
        bear["key_factors"] = [typed_claim("The neutral research view may limit downside conviction.",
                                           ["research_view.direction"], evidence_type="RESEARCH_VIEW")]
        risk = valid_report("risk", self.digest)
        risk["risk_factors"] = [typed_claim("The evidence suggests conflicting risk.",
                                            ["research_view.why"], claim_type="RISK",
                                            support_type="DERIVED", evidence_type="RESEARCH_VIEW")]
        risk["evidence_ids"] = sorted({reference for key in
            ("risk_factors", "conflicts", "model_risks", "data_risks", "event_risks",
             "missing_evidence", "limitations", "uncertainty")
            for claim in risk[key] for reference in claim["evidence_ids"]})
        for name, report in (("bull", bull), ("bear", bear), ("risk", risk)):
            self.assertEqual(validate_output(report, name, self.digest, self.catalog), report)

    def test_material_claim_without_evidence_is_rejected(self):
        report = valid_report("bull", self.digest)
        report["key_factors"] = [typed_claim("The signal may be constructive.", [],
                                             evidence_type="TECHNICAL")]
        with self.assertRaises(ClaimValidationError):
            validate_output(report, "bull", self.digest, self.catalog)

    def test_nonexistent_source_is_rejected(self):
        report = valid_report("bear", self.digest)
        report["key_factors"] = [typed_claim("The signal may be weak.", ["news.article.999"],
                                             evidence_type="NEWS")]
        with self.assertRaises(ClaimValidationError):
            validate_output(report, "bear", self.digest, self.catalog)

    def test_fact_framing_with_interpretive_evidence_is_rejected(self):
        report = copy.deepcopy(valid_report("bear", self.digest))
        report["key_factors"] = [typed_claim("Customer demand is weakening.", ["research_view.why"],
                                             claim_type="FACT", support_type="DIRECT",
                                             evidence_type="RESEARCH_VIEW")]
        with self.assertRaises(ClaimValidationError):
            validate_output(report, "bear", self.digest, self.catalog)

    def test_claim_object_has_typed_fact_interpretation_contract(self):
        schema = output_schema("bull", allowed_evidence_ids(self.catalog))
        properties = schema["properties"]["key_factors"]["items"]["properties"]
        self.assertEqual(set(properties), {"text", "claim_type", "support_type", "evidence_type",
                                           "evidence_ids", "confidence", "material", "field_key", "value", "unit", "direction"})
        self.assertIn("FACT", properties["claim_type"]["enum"])
        self.assertIn("INTERPRETATION", properties["claim_type"]["enum"])


if __name__ == "__main__":
    unittest.main()
