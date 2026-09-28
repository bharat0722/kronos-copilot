"""Offline snapshot-scoped citation schema and harness checks."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_research import (AGENTS, MAX_REASONING_ROUNDS, MAX_RETRIES, AgentTeam,
                                ClaimValidationError, NumericalGroundingError,
                                allowed_evidence_ids, evidence_catalog, output_schema,
                                validate_output)
from app.evidence_snapshot import snapshot_id
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response, synthetic_record
from research.tests.test_phase7_agents import valid_report


def citation_items(schema: dict) -> list[dict]:
    items = []
    for name, field in schema["properties"].items():
        if name in ("evidence_ids", "supporting_evidence_ids", "contradicting_evidence_ids"):
            items.append(field["items"])
        elif name in ("key_factors", "risk_factors", "conflicts", "model_risks", "data_risks", "event_risks"):
            items.append(field["items"]["properties"]["evidence_ids"]["items"])
    return items


class Phase72CEvidenceIdTests(unittest.TestCase):
    def setUp(self):
        self.record = synthetic_record()
        self.digest = self.record["snapshot_id"]
        self.catalog = evidence_catalog(self.record["evidence"])
        self.ids = allowed_evidence_ids(self.catalog)

    def test_catalog_is_deterministic_scoped_and_has_no_empty_values(self):
        self.assertEqual(self.ids, tuple(sorted(set(self.ids))))
        self.assertEqual(self.ids, allowed_evidence_ids(evidence_catalog(self.record["evidence"])))
        self.assertIn("news.article.0", self.ids)
        self.assertIn("news.article.1", self.ids)
        self.assertIn("technicals.indicator.0", self.ids)
        self.assertIn("kronos.direction", self.ids)
        self.assertTrue(all(self.catalog[reference] is not None for reference in self.ids))
        self.assertNotIn("news.event.0", self.ids)
        self.assertNotIn("NEWS_99", self.ids)
        self.assertEqual(allowed_evidence_ids({"missing": None, "present": "value"}), ("present",))

    def test_all_agent_citation_fields_use_the_same_snapshot_enum(self):
        with tempfile.TemporaryDirectory() as directory:
            team = AgentTeam(Path(directory), client_factory=lambda: self.fail("No network"))
            self.assertEqual(team.preflight(self.record)["status"], "PASS")
            wire = json.dumps({"evidence": self.record["evidence"]}).encode()
            for name in AGENTS:
                with self.subTest(agent=name):
                    schema = team._request_args(name, wire)["text"]["format"]["schema"]
                    self.assertEqual(schema, output_schema(name, self.ids))
                    self.assertTrue(citation_items(schema))
                    self.assertTrue(all(item == {"type": "string", "enum": list(self.ids)}
                                        for item in citation_items(schema)))
                    self.assertTrue(all("NEWS_99" not in item["enum"] for item in citation_items(schema)))
                    self.assertTrue(all("TECH_999" not in item["enum"] for item in citation_items(schema)))
                    self.assertTrue(all("KRONOS_DOES_NOT_EXIST" not in item["enum"]
                                        for item in citation_items(schema)))
                    self.assertLess(len(json.dumps(schema)), 20_000)
            self.assertFalse(Path(directory).joinpath("openai_usage.sqlite3").exists())

    def test_schema_cannot_be_built_without_citable_ids(self):
        for name in AGENTS:
            with self.subTest(agent=name), self.assertRaisesRegex(ValueError, "no citable"):
                output_schema(name, ())

    def test_different_snapshot_catalogs_produce_independent_schemas_and_cache_keys(self):
        changed = copy.deepcopy(self.record["evidence"])
        changed["news"]["article_evidence"].pop()
        changed_record = {"evidence": changed, "snapshot_id": snapshot_id(changed)}
        changed_ids = allowed_evidence_ids(evidence_catalog(changed))
        self.assertNotIn("news.article.2", changed_ids)
        self.assertIn("news.article.2", self.ids)
        self.assertNotEqual(output_schema("bull", self.ids), output_schema("bull", changed_ids))
        with tempfile.TemporaryDirectory() as directory:
            team = AgentTeam(Path(directory), client_factory=lambda: self.fail("No network"))
            self.assertNotEqual(team._key(self.digest, "bull"), team._key(changed_record["snapshot_id"], "bull"))
            self.assertEqual(team.preflight(changed_record)["status"], "PASS")

    def test_valid_single_and_multiple_citations_and_empty_claim_rejection(self):
        for name in AGENTS:
            with self.subTest(agent=name):
                report = valid_report(name, self.digest)
                field = "risk_factors" if name == "risk" else "key_factors"
                report[field][0]["evidence_ids"] = ["news.article.0"]
                self.assertEqual(validate_output(report, name, self.digest, self.catalog), report)
                report[field][0]["evidence_ids"] = ["news.article.0", "news.article.1"]
                self.assertEqual(validate_output(report, name, self.digest, self.catalog), report)
                report[field][0]["evidence_ids"] = []
                with self.assertRaises(ClaimValidationError):
                    validate_output(report, name, self.digest, self.catalog)

    def test_fabricated_and_mixed_ids_fail_local_validation(self):
        for name in AGENTS:
            for ids in (["NEWS_FAKE"], ["TECH_999"], ["KRONOS_DOES_NOT_EXIST"],
                        ["news.article.0", "NEWS_FAKE"]):
                with self.subTest(agent=name, ids=ids):
                    report = valid_report(name, self.digest)
                    field = "risk_factors" if name == "risk" else "key_factors"
                    report[field][0]["evidence_ids"] = ids
                    with self.assertRaises(ClaimValidationError):
                        validate_output(report, name, self.digest, self.catalog)

    def test_numerical_grounding_remains_strict(self):
        for name in AGENTS:
            with self.subTest(agent=name):
                report = valid_report(name, self.digest)
                field = "risk_factors" if name == "risk" else "key_factors"
                report[field][0] = {"text": "The saved forecast change is 2%.",
                                    "evidence_ids": ["kronos.forecast_pct_change"]}
                self.assertEqual(validate_output(report, name, self.digest, self.catalog), report)
                report[field][0]["text"] = "The saved forecast change is 40%."
                with self.assertRaises(NumericalGroundingError):
                    validate_output(report, name, self.digest, self.catalog)

    def test_mock_valid_output_passes_schema_validator_ledger_and_cache(self):
        client = MockClient(lambda name: mock_response(name, self.digest))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            team = AgentTeam(root, client_factory=lambda: client)
            result = team.run(self.record)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["api_calls"], 3)
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(len(list((root / "runs").glob("*.json"))), 3)
            self.assertEqual(len(list((root / "cache").glob("*.json"))), 3)
            for name, call in zip(AGENTS, client.calls):
                self.assertEqual(call["text"]["format"]["schema"], output_schema(name, self.ids))
                self.assertEqual(call["max_output_tokens"], 900)
                self.assertEqual(call["tools"], [])
                self.assertEqual(call["tool_choice"], "none")
            self.assertEqual(team.result(self.record)["status"], "CACHED")

    def test_mock_fabricated_ids_fail_before_publication_or_cache(self):
        def response(name):
            report = valid_report(name, self.digest)
            field = "risk_factors" if name == "risk" else "key_factors"
            report[field][0]["evidence_ids"] = ["news.article.0", "NEWS_FAKE"]
            return mock_response(name, self.digest, report=report)
        client = MockClient(response)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            team = AgentTeam(root, client_factory=lambda: client)
            result = team.run(self.record)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["api_calls"], 6)
            self.assertTrue(all(result["agents"][name]["report"] is None for name in AGENTS))
            self.assertFalse((root / "cache").exists())
            attempts = [json.loads(path.read_text()) for path in (root / "attempts").glob("*.json")]
            self.assertEqual(len(attempts), 6)
            self.assertTrue(all(row["failure_stage"] == "CLAIM_VALIDATION" for row in attempts))
            self.assertTrue(all(row["retry_decision"] == ("RETRY" if row["attempt"] == 1 else "STOP")
                                for row in attempts))
            self.assertTrue(all("NEWS_FAKE" not in json.dumps(call["text"]["format"]["schema"])
                                for call in client.calls))

    def test_snapshot_a_cache_is_not_reused_for_snapshot_b(self):
        changed = copy.deepcopy(self.record["evidence"])
        changed["news"]["article_evidence"].pop()
        changed_record = {"evidence": changed, "snapshot_id": snapshot_id(changed)}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            client = MockClient(lambda name: mock_response(name, self.digest))
            team = AgentTeam(root, client_factory=lambda: client)
            self.assertEqual(team.run(self.record)["status"], "SUCCESS")
            self.assertEqual(team.result(changed_record)["status"], "READY")
            self.assertEqual(team.run(self.record)["status"], "CACHED")
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(len(list((root / "cache").glob("*.json"))), 3)

    def test_limits_remain_frozen(self):
        self.assertEqual(MAX_REASONING_ROUNDS, 1)
        self.assertEqual(MAX_RETRIES, 1)
        self.assertEqual(AgentTeam(Path("unused")).config.model, "gpt-5-mini")
        self.assertEqual(AgentTeam(Path("unused")).config.max_output_tokens, 900)


if __name__ == "__main__":
    unittest.main()
