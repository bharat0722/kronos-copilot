"""Offline Bull numerical-grounding and rejection-diagnostic regression tests."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import agent_research
from app.agent_research import (AGENTS, MAX_REASONING_ROUNDS, MAX_RETRIES, AgentTeam,
                                ClaimValidationError, NumericalGroundingError,
                                PROMPT_VERSIONS, evidence_catalog, validate_output)
from app.evidence_snapshot import snapshot_id
from research.tests.test_phase7_2a_diagnostics import MockClient, mock_response, synthetic_record
from research.tests.test_phase7_agents import valid_report


def record_with(**changes):
    content = copy.deepcopy(synthetic_record()["evidence"])
    for section, values in changes.items():
        content[section].update(values)
    return {"evidence": content, "snapshot_id": snapshot_id(content)}


def bull_claim(record, text, references, *, argument=False):
    report = valid_report("bull", record["snapshot_id"])
    if argument:
        report["argument"] = text
        report["supporting_evidence_ids"] = references
    else:
        report["key_factors"] = [{"text": text, "evidence_ids": references}]
    return report


class BullNumericalGroundingTests(unittest.TestCase):
    def setUp(self):
        self.record = synthetic_record()
        self.catalog = evidence_catalog(self.record["evidence"])

    def validate(self, record, report):
        return validate_output(report, "bull", record["snapshot_id"], evidence_catalog(record["evidence"]))

    def test_supported_forecast_percentage_and_decimal_normalization(self):
        for text in ("The cited forecast shows +2%.", "The cited forecast shows +2.0%.",
                     "The saved forecast change is 2.00 percent."):
            with self.subTest(text=text):
                report = bull_claim(self.record, text, ["kronos.forecast_pct_change"])
                self.assertEqual(self.validate(self.record, report), report)

    def test_unsupported_15_percent_rejected_with_diagnostic(self):
        report = bull_claim(self.record, "TESTCO offers 15% upside", ["kronos.forecast_pct_change"])
        with self.assertRaises(NumericalGroundingError) as context:
            self.validate(self.record, report)
        diagnostic = context.exception.diagnostic
        self.assertEqual(diagnostic["claim_id"], "key_factors.0")
        self.assertEqual(diagnostic["claim_text"], "TESTCO offers 15% upside")
        self.assertEqual(diagnostic["numbers_found"], ["15%"])
        self.assertEqual(diagnostic["unsupported_numbers"], ["15%"])
        self.assertEqual(diagnostic["evidence_ids"], ["kronos.forecast_pct_change"])
        self.assertTrue(any(item["value"] == "2.0" and item["unit"] == "percent"
                            for item in diagnostic["supported_numbers"]))
        self.assertEqual(diagnostic["failure_reason"], "unsupported_numerical_claim")

    def test_supported_rsi_needs_rsi_indicator(self):
        content = copy.deepcopy(self.record["evidence"])
        content["technicals"]["values"][0]["value"] = 62
        record = {"evidence": content, "snapshot_id": snapshot_id(content)}
        report = bull_claim(record, "RSI is 62", ["technicals.indicator.0"])
        self.assertEqual(self.validate(record, report), report)

    def test_same_number_in_news_cannot_ground_rsi(self):
        content = copy.deepcopy(self.record["evidence"])
        content["news"]["article_evidence"][0]["summary"] = "Company opened 62 stores."
        content["news"]["article_evidence"][0]["relevance"] = 62
        record = {"evidence": content, "snapshot_id": snapshot_id(content)}
        report = bull_claim(record, "RSI is 62", ["news.article.0"])
        with self.assertRaises(NumericalGroundingError) as context:
            self.validate(record, report)
        self.assertEqual(context.exception.diagnostic["failure_reason"], "field_or_unit_mismatch")

    def test_price_currency_and_comma_normalization(self):
        record = record_with(market_data={"last_observed_close": 1000, "currency": "INR"})
        for text in ("Price is \u20b91,000", "Price is \u20b91000.00", "Price is 1000"):
            with self.subTest(text=text):
                report = bull_claim(record, text, ["market_data.last_observed_close", "market_data.currency"])
                self.assertEqual(self.validate(record, report), report)

    def test_invented_target_and_wrong_currency_rejected(self):
        record = record_with(market_data={"last_observed_close": 100, "currency": "INR"})
        for text in ("Price target is \u20b9120", "Price is $100"):
            with self.subTest(text=text):
                report = bull_claim(record, text, ["market_data.last_observed_close", "market_data.currency"])
                with self.assertRaises(NumericalGroundingError):
                    self.validate(record, report)

    def test_explicit_currency_requires_cited_metadata(self):
        record = record_with(market_data={"last_observed_close": 100, "currency": "INR"})
        report = bull_claim(record, "Price is \u20b9100", ["market_data.last_observed_close"])
        with self.assertRaises(NumericalGroundingError):
            self.validate(record, report)

    def test_explicit_currency_without_metadata_rejected(self):
        report = bull_claim(self.record, "Price is \u20b9100", ["kronos.last_observed_close"])
        with self.assertRaises(NumericalGroundingError):
            self.validate(self.record, report)

    def test_percentage_unit_mismatch_is_not_silently_converted(self):
        for text in ("The forecast change is 2", "The forecast change is 0.02"):
            with self.subTest(text=text):
                report = bull_claim(self.record, text, ["kronos.forecast_pct_change"])
                with self.assertRaises(NumericalGroundingError):
                    self.validate(self.record, report)

    def test_uncited_numeric_and_unknown_reference_rejected(self):
        report = bull_claim(self.record, "The forecast change is 2%", [], argument=True)
        report["contradicting_evidence_ids"] = []
        with self.assertRaises(ClaimValidationError):
            self.validate(self.record, report)
        report = bull_claim(self.record, "The forecast change is 2%", ["KRONOS_01"])
        with self.assertRaises(ClaimValidationError):
            self.validate(self.record, report)

    def test_grounded_qualitative_claim_and_structural_word_count(self):
        for text in ("The cited RSI signal is bullish.", "The evidence presents two risks."):
            with self.subTest(text=text):
                report = bull_claim(self.record, text, ["technicals.indicator.0"])
                self.assertEqual(self.validate(self.record, report), report)

    def test_qualitative_entailment_is_not_claimed_by_numeric_guard(self):
        report = bull_claim(self.record, "The company has a durable moat.", ["technicals.indicator.0"])
        self.assertEqual(self.validate(self.record, report), report)

    def test_raw_secret_and_path_redacted_from_diagnostic(self):
        secret = "offline-secret-123456789"
        text = "Forecast upside is 15%; token=" + secret + " at C:\\private\\secret.txt for alice@example.org"
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}):
            report = bull_claim(self.record, text, ["kronos.forecast_pct_change"])
            with self.assertRaises(NumericalGroundingError) as context:
                self.validate(self.record, report)
        diagnostic_text = json.dumps(context.exception.diagnostic)
        self.assertNotIn(secret, diagnostic_text)
        self.assertNotIn("C:\\private", diagnostic_text)
        self.assertNotIn("alice@example.org", diagnostic_text)
        self.assertIn("15%", diagnostic_text)

    def test_prompt_version_and_cache_key_are_bull_only(self):
        self.assertEqual(PROMPT_VERSIONS["bull"], "bull_agent_prompt_v4")
        self.assertEqual(PROMPT_VERSIONS["bear"], "bear_agent_prompt_v3")
        self.assertEqual(PROMPT_VERSIONS["risk"], "risk_agent_prompt_v3")
        team = AgentTeam(Path("unused"))
        current = {name: team._key(self.record["snapshot_id"], name) for name in AGENTS}
        with patch.dict(PROMPT_VERSIONS, {"bull": "bull_agent_prompt_v3"}):
            old = {name: team._key(self.record["snapshot_id"], name) for name in AGENTS}
        self.assertNotEqual(current["bull"], old["bull"])
        self.assertEqual(current["bear"], old["bear"])
        self.assertEqual(current["risk"], old["risk"])

    def test_rejection_is_attempt_only_and_never_cached(self):
        def response(name):
            report = valid_report(name, self.record["snapshot_id"])
            if name == "bull":
                report["key_factors"] = [{"text": "TESTCO offers 15% upside",
                                          "evidence_ids": ["kronos.forecast_pct_change"]}]
            return mock_response(name, self.record["snapshot_id"], report=report)
        client = MockClient(response)
        original = copy.deepcopy(self.record)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            team = AgentTeam(root, client_factory=lambda: client)
            result = team.run(self.record)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["api_calls"], 4)
            self.assertIsNone(result["agents"]["bull"]["report"])
            self.assertEqual(len(list((root / "cache").glob("*.json"))), 2)
            self.assertTrue(all(item["report"]["agent_type"] != "bull" for path in (root / "cache").glob("*.json")
                                for item in [json.loads(path.read_text())]))
            attempts = [json.loads(path.read_text()) for path in (root / "attempts").glob("*.json")]
            bull_attempts = sorted((row for row in attempts if row["agent_type"] == "bull"),
                                   key=lambda row: row["attempt"])
            self.assertEqual(len(bull_attempts), 2)
            self.assertEqual([row["retry_decision"] for row in bull_attempts], ["RETRY", "STOP"])
            self.assertTrue(all(row["failure_stage"] == "NUMERICAL_GROUNDING" and
                                row["schema_version"] == "agent_attempt_v2" and
                                row["validation_diagnostic"]["unsupported_numbers"] == ["15%"]
                                for row in bull_attempts))
            parent = next(json.loads(path.read_text()) for path in (root / "runs").glob("*.json")
                          if json.loads(path.read_text())["agent_type"] == "bull")
            self.assertEqual(parent["validation_diagnostic_attempt_refs"], parent["attempt_refs"])
            self.assertEqual(team.result(self.record)["agents"]["bull"]["status"], "NOT_RUN")
        self.assertEqual(self.record, original)

    def test_first_attempt_diagnostic_survives_successful_retry_and_ledger_precedes_cache(self):
        counts = {name: 0 for name in AGENTS}
        def response(name):
            counts[name] += 1
            report = valid_report(name, self.record["snapshot_id"])
            if name == "bull" and counts[name] == 1:
                report["key_factors"] = [{"text": "TESTCO offers 15% upside",
                                          "evidence_ids": ["kronos.forecast_pct_change"]}]
            return mock_response(name, self.record["snapshot_id"], report=report)
        client = MockClient(response)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            team = AgentTeam(root, client_factory=lambda: client)
            events = []
            original_ledger = team._ledger
            original_atomic = agent_research._atomic_json
            def ledger(row):
                events.append(("ledger", row["agent_type"], row["cache_status"]))
                original_ledger(row)
            def atomic(path, value):
                if path.parent.name == "cache":
                    events.append(("cache", value["report"]["agent_type"], None))
                original_atomic(path, value)
            with patch.object(team, "_ledger", side_effect=ledger), patch.object(agent_research, "_atomic_json", side_effect=atomic):
                result = team.run(self.record)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["api_calls"], 4)
            self.assertEqual([e for e in events if e[1] == "bull"],
                             [("ledger", "bull", "PENDING"), ("cache", "bull", None), ("ledger", "bull", "STORED")])
            parent = next(json.loads(path.read_text()) for path in (root / "runs").glob("*.json")
                          if json.loads(path.read_text())["agent_type"] == "bull")
            self.assertEqual(parent["status"], "SUCCESS")
            self.assertEqual(parent["retry_count"], 1)
            self.assertEqual(parent["validation_diagnostic_attempt_refs"], [parent["attempt_refs"][0]])
            first = json.loads((root / "attempts" / (parent["attempt_refs"][0] + ".json")).read_text())
            second = json.loads((root / "attempts" / (parent["attempt_refs"][1] + ".json")).read_text())
            self.assertEqual(first["validation_diagnostic"]["unsupported_numbers"], ["15%"])
            self.assertEqual(second["status"], "SUCCESS")
            self.assertNotIn("validation_diagnostic", second)
            self.assertEqual(team.result(self.record)["status"], "CACHED")

    def test_old_bull_prompt_cache_is_not_reused(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            team = AgentTeam(Path(directory), client_factory=lambda: client)
            with patch.dict(PROMPT_VERSIONS, {"bull": "bull_agent_prompt_v3"}):
                self.assertEqual(team.run(self.record)["status"], "SUCCESS")
            result = team.result(self.record)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["agents"]["bull"]["status"], "NOT_RUN")
            self.assertEqual(result["agents"]["bear"]["status"], "CACHED")
            self.assertEqual(result["agents"]["risk"]["status"], "CACHED")

    def test_bear_risk_and_frozen_limits(self):
        for name in ("bear", "risk"):
            with self.subTest(agent=name):
                report = valid_report(name, self.record["snapshot_id"])
                self.assertEqual(validate_output(report, name, self.record["snapshot_id"], self.catalog), report)
        self.assertEqual(MAX_REASONING_ROUNDS, 1)
        self.assertEqual(MAX_RETRIES, 1)
        team = AgentTeam(Path("unused"))
        self.assertEqual(team.config.model, "gpt-5-mini")
        self.assertEqual(team.config.max_output_tokens, 900)
        request = team._request_args("bull", agent_research.canonical_bytes(
            {"evidence": self.record["evidence"], "evidence_catalog": self.catalog}))
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")


if __name__ == "__main__":
    unittest.main()
