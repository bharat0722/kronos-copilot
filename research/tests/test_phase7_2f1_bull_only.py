"""Offline tests for the supported Phase 7.2F.1 Bull-only harness path."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_research import (AGENTS, MAX_REASONING_ROUNDS, MAX_RETRIES,
                                AgentConfig, AgentError, AgentTeam, PROMPT_VERSIONS)
from app.evidence_snapshot import canonical_bytes, snapshot_id
from research.tests.test_phase7_2a_diagnostics import (MockClient, mock_response,
                                                       synthetic_record)
from research.tests.test_phase7_agents import typed_claim, valid_report


EXPECTED_TESTCO_HASH = "23743eab11f55ca96c1811428353f793a922363d6fd99c823cff71bb4c67f58a"


def _rows(root: Path, folder: str) -> list[dict]:
    path = root / folder
    return [json.loads(item.read_text(encoding="utf-8")) for item in path.glob("*.json")] if path.exists() else []


class BullOnlyHarnessTests(unittest.TestCase):
    def setUp(self):
        self.record = synthetic_record()

    def test_bull_only_pass_uses_one_bull_call(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            result = AgentTeam(Path(directory), client_factory=lambda: client).run_bull_only(self.record)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["agent_type"], "bull")
        self.assertEqual(result["agent"]["report"]["agent_type"], "bull")
        self.assertEqual(result["api_calls"], 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["text"]["format"]["name"], "bull_agent_report_v2")

    def test_bull_only_requires_configured_key_before_client(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            team = AgentTeam(Path(directory), client_factory=lambda: self.fail("Client must not be constructed"))
            with self.assertRaises(AgentError) as context:
                team.run_bull_only(self.record)
        self.assertEqual(context.exception.code, "UNAVAILABLE")
        self.assertEqual(team._api_calls, 0)

    def test_bull_only_invalid_number_retries_once_and_is_not_cached(self):
        def rejected(name):
            report = valid_report(name, self.record["snapshot_id"])
            report["key_factors"] = [typed_claim("TESTCO offers 15% upside",
                                                 ["kronos.forecast_pct_change"],
                                                 claim_type="NUMERICAL_FACT", support_type="DIRECT")]
            return mock_response(name, self.record["snapshot_id"], report=report)
        client = MockClient(rejected)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            attempts = sorted(_rows(root, "attempts"), key=lambda row: row["attempt"])
            caches = _rows(root, "cache")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["api_calls"], 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual([row["retry_decision"] for row in attempts], ["RETRY", "STOP"])
        self.assertTrue(all(row["failure_stage"] == "NUMERICAL_GROUNDING" for row in attempts))
        self.assertTrue(all(row["validation_diagnostic"]["unsupported_numbers"] == ["15%"] for row in attempts))
        self.assertEqual(caches, [])

    def test_bull_only_first_rejected_then_passes(self):
        calls = 0
        def response(name):
            nonlocal calls
            calls += 1
            report = valid_report(name, self.record["snapshot_id"])
            if calls == 1:
                report["key_factors"] = [typed_claim("TESTCO offers 15% upside",
                                                     ["kronos.forecast_pct_change"],
                                                     claim_type="NUMERICAL_FACT", support_type="DIRECT")]
            return mock_response(name, self.record["snapshot_id"], report=report)
        client = MockClient(response)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            parent = _rows(root, "runs")[0]
            attempts = sorted(_rows(root, "attempts"), key=lambda row: row["attempt"])
            caches = _rows(root, "cache")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["api_calls"], 2)
        self.assertEqual(parent["retry_count"], 1)
        self.assertEqual(parent["validation_diagnostic_attempt_refs"], [attempts[0]["attempt_id"]])
        self.assertEqual(len(caches), 1)

    def test_bull_only_invalid_json_fails_cleanly(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"], text="{bad json"))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            attempts = _rows(root, "attempts")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["api_calls"], 2)
        self.assertTrue(all(row["failure_stage"] == "STRUCTURED_PARSE" for row in attempts))

    def test_bull_only_invalid_citation_is_rejected(self):
        def rejected(name):
            report = valid_report(name, self.record["snapshot_id"])
            report["supporting_evidence_ids"] = ["fabricated.reference"]
            return mock_response(name, self.record["snapshot_id"], report=report)
        client = MockClient(rejected)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            attempts = _rows(root, "attempts")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(row["failure_stage"] == "CLAIM_VALIDATION" for row in attempts))

    def test_bull_only_refusal_is_not_published(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"], content_type="refusal"))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            result = AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            attempts = _rows(root, "attempts")
        self.assertEqual(result["status"], "FAILED")
        self.assertIsNone(result["agent"]["report"])
        self.assertTrue(all(row["failure_stage"] == "RESPONSE_REFUSAL" for row in attempts))
        self.assertEqual(_rows(root, "cache"), [])

    def test_bull_only_exception_respects_retry_ceiling(self):
        client = MockClient(lambda name: (_ for _ in ()).throw(TimeoutError("offline timeout")))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            result = AgentTeam(Path(directory), client_factory=lambda: client).run_bull_only(self.record)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["api_calls"], MAX_RETRIES + 1)
        self.assertEqual(len(client.calls), MAX_RETRIES + 1)

    def test_bull_only_cache_hit_and_identity(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            team = AgentTeam(root, client_factory=lambda: client)
            first = team.run_bull_only(self.record)
            second = team.run_bull_only(self.record)
            base_key = team._key(self.record["snapshot_id"], "bull")
            changed = copy.deepcopy(self.record["evidence"])
            changed["kronos"]["direction"] = "down"
            changed_hash = snapshot_id(changed)
            with patch.dict(PROMPT_VERSIONS, {"bull": "bull_agent_prompt_v3"}):
                old_prompt_key = team._key(self.record["snapshot_id"], "bull")
            other_model_key = AgentTeam(root, config=AgentConfig(model="offline-other-model"))._key(
                self.record["snapshot_id"], "bull")
        self.assertEqual(first["status"], "SUCCESS")
        self.assertEqual(second["status"], "CACHED")
        self.assertEqual(len(client.calls), 1)
        self.assertNotEqual(base_key, team._key(changed_hash, "bull"))
        self.assertNotEqual(base_key, old_prompt_key)
        self.assertNotEqual(base_key, other_model_key)

    def test_bull_only_ledger_uses_existing_contract(self):
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            root = Path(directory)
            AgentTeam(root, client_factory=lambda: client).run_bull_only(self.record)
            parent = _rows(root, "runs")[0]
            attempt = _rows(root, "attempts")[0]
        self.assertEqual(parent["schema_version"], "agent_run_v3")
        self.assertEqual(parent["agent_type"], "bull")
        self.assertEqual(parent["prompt_version"], "bull_agent_prompt_v5")
        self.assertEqual(parent["model"], "gpt-5-mini")
        self.assertEqual(parent["status"], "SUCCESS")
        self.assertEqual(parent["cache_status"], "STORED")
        self.assertEqual(parent["attempt_refs"], [attempt["attempt_id"]])
        self.assertEqual(attempt["agent_type"], "bull")
        self.assertEqual(attempt["token_usage"]["total_tokens"], 170)

    def test_bull_only_preserves_evidence_immutability(self):
        original = canonical_bytes(self.record)
        client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            AgentTeam(Path(directory), client_factory=lambda: client).run_bull_only(self.record)
        self.assertEqual(canonical_bytes(self.record), original)

    def test_testco_preflight_limits_and_no_tools(self):
        self.assertEqual(self.record["snapshot_id"], EXPECTED_TESTCO_HASH)
        self.assertEqual(self.record["evidence"]["instrument"]["canonical_symbol"], "NSE:TESTCO")
        team = AgentTeam(Path("unused"), client_factory=lambda: self.fail("No client expected"))
        preflight = team.preflight(self.record)
        self.assertEqual(preflight["status"], "PASS")
        self.assertEqual(team.config.model, "gpt-5-mini")
        self.assertEqual(team.config.max_output_tokens, 900)
        self.assertEqual(MAX_REASONING_ROUNDS, 1)
        self.assertEqual(MAX_RETRIES, 1)
        digest, catalog, wire = team._prepare(self.record, ("bull",))
        self.assertEqual(digest, EXPECTED_TESTCO_HASH)
        request = team._request_args("bull", wire)
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        self.assertFalse(request["parallel_tool_calls"])
        self.assertEqual(PROMPT_VERSIONS["bull"], "bull_agent_prompt_v5")
        self.assertTrue(catalog)

    def test_result_is_bull_specific_and_default_team_is_unchanged(self):
        bull_client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        team_client = MockClient(lambda name: mock_response(name, self.record["snapshot_id"]))
        with tempfile.TemporaryDirectory() as bull_dir, tempfile.TemporaryDirectory() as team_dir, \
                patch.dict(os.environ, {"OPENAI_API_KEY": "offline-only"}):
            bull = AgentTeam(Path(bull_dir), client_factory=lambda: bull_client).run_bull_only(self.record)
            team = AgentTeam(Path(team_dir), client_factory=lambda: team_client).run(self.record)
        self.assertEqual(set(bull), {"snapshot_id", "agent_type", "status", "agent", "latency_ms", "api_calls"})
        self.assertNotIn("agents", bull)
        self.assertEqual(list(team["agents"]), list(AGENTS))
        self.assertEqual(team["agents_completed"], 3)
        self.assertEqual(team["api_calls"], 3)
        self.assertEqual([call["text"]["format"]["name"] for call in team_client.calls],
                         ["bull_agent_report_v2", "bear_agent_report_v2", "risk_agent_report_v2"])
        self.assertEqual(PROMPT_VERSIONS,
                         {"bull": "bull_agent_prompt_v5", "bear": "bear_agent_prompt_v4",
                          "risk": "risk_agent_prompt_v4"})


if __name__ == "__main__":
    unittest.main()
