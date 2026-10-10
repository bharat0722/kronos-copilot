"""Offline failure-stage, attempt-ledger, and response-metadata checks."""

from __future__ import annotations
from research.tests.legacy_agent_harness import LegacyAgentTeam

import json
import inspect
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openai import (APIConnectionError, APIResponseValidationError, APITimeoutError, AuthenticationError, BadRequestError,
                    InternalServerError, RateLimitError)
from openai._exceptions import httpx2
from openai.resources.responses.responses import Responses
from openai.types.responses import Response

from app import agent_research
from app.agent_research import AgentError, AgentTeam, FailureStage
from app.evidence_snapshot import canonical_bytes, snapshot_id
from research.tests.test_phase7_agents import valid_report, concise_report


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CLOCK = datetime.now(timezone.utc).isoformat()


def synthetic_record():
    content = json.loads((Path(__file__).parent / "fixtures/synthetic_agent_evidence.json").read_text(encoding="utf-8"))
    stamp = FIXTURE_CLOCK
    content["market_data"]["retrieved_at"] = stamp
    content["news"]["retrieved_at"] = stamp
    return {"snapshot_id": snapshot_id(content), "created_at": stamp, "evidence": content}


def mock_response(name, digest, *, report=None, status="completed", text=None, usage=True,
                  content_type="output_text", incomplete_reason=None):
    value = valid_report(name, digest) if report is None else report
    output_text = json.dumps(value) if text is None else text
    return SimpleNamespace(
        id="resp_offline", _request_id="req_offline", model="gpt-5-mini", status=status,
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type=content_type,
                                                                              text=output_text)])],
        output_text=output_text,
        incomplete_details=SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None,
        error=None,
        usage=SimpleNamespace(input_tokens=100, output_tokens=70, total_tokens=170) if usage else None,
    )


def sdk_response(name, digest):
    return Response.model_validate({
        "id": "resp_offline", "created_at": 0, "model": "gpt-5-mini", "object": "response",
        "output": [{"id": "msg_offline", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(concise_report(valid_report(name, digest))),
                                 "annotations": []}]}],
        "parallel_tool_calls": False, "tool_choice": "none", "tools": [], "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 70, "total_tokens": 170,
                  "input_tokens_details": {"cache_write_tokens": 0, "cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    })


class MockClient:
    def __init__(self, make_response):
        self.make_response = make_response
        self.responses = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["text"]["format"]["name"].split("_", 1)[0]
        response = self.make_response(name)
        # Bound valid mocks; keep unsupported responses intact for rejection tests.
        if isinstance(response, SimpleNamespace) and getattr(response, "status", None) == "completed":
            try:
                report = json.loads(response.output_text)
                wire = json.loads(kwargs["input"].split("\n", 1)[1])
                agent_research.validate_output(report, name, wire["snapshot_id"],
                                              agent_research.evidence_catalog(wire["evidence"]))
                response.output_text = json.dumps(concise_report(report))
            except (ValueError, KeyError, TypeError):
                pass
        return response


class Phase72ADiagnosticsTests(unittest.TestCase):
    def run_offline(self, make_response):
        record = synthetic_record()
        client = MockClient(make_response)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-only"}):
            root = Path(directory)
            team = LegacyAgentTeam(root, client_factory=lambda: client)
            result = team.run(record)
            parents = {row["agent_type"]: row for path in (root / "runs").glob("*.json")
                       for row in [json.loads(path.read_text(encoding="utf-8"))]}
            attempts = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "attempts").glob("*.json")]
            cache_count = len(list((root / "cache").glob("*.json"))) if (root / "cache").exists() else 0
            budget = team.usage.totals("openai_agents")[0]
            return result, parents, attempts, cache_count, budget, client.calls

    def test_synthetic_preflight_and_strict_schema_without_network(self):
        record = synthetic_record()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "unused"
            team = LegacyAgentTeam(root, client_factory=lambda: self.fail("No client should be constructed"))
            result = team.preflight(record)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["model"], "gpt-5-mini")
            self.assertEqual(result["tools"], "none")
            self.assertLessEqual(result["input_bytes"], team.config.max_input_bytes)
            self.assertFalse(root.exists())

            wire = canonical_bytes({"snapshot_id": record["snapshot_id"], "evidence": record["evidence"],
                                    "evidence_catalog": agent_research.evidence_catalog(record["evidence"])})
            request = team._request_args("bull", wire)
            self.assertTrue(set(request).issubset(inspect.signature(Responses.create).parameters))
            self.assertEqual(request["text"]["format"]["type"], "json_schema")
            self.assertTrue(request["text"]["format"]["strict"])

            original = agent_research.output_schema
            def unsupported(name, allowed_ids):
                schema = original(name, allowed_ids)
                schema["properties"]["snapshot_id"]["minLength"] = 1
                return schema
            with patch.object(agent_research, "output_schema", side_effect=unsupported):
                with self.assertRaises(AgentError) as failure:
                    team.run(record)
            self.assertEqual(failure.exception.code, "PREFLIGHT_FAILED")
            self.assertEqual(failure.exception.stage, FailureStage.PRE_REQUEST_VALIDATION)
            self.assertFalse(root.exists())

    def test_safe_identifiers_never_preserve_credential_shapes(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-secret-123456"}):
            self.assertIsNone(agent_research._safe_identifier("offline-secret-123456"))
            self.assertIsNone(agent_research._safe_identifier("sk-proj-offline-secret"))
            self.assertIsNone(agent_research._safe_identifier("tvly-offline-secret"))
            self.assertEqual(agent_research._safe_identifier("req_offline"), "req_offline")

    def test_api_status_errors_keep_safe_status_and_do_not_retry_client_errors(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for exception_type, http_status, stage, calls in (
                (BadRequestError, 400, "API_ERROR", 3),
                (AuthenticationError, 401, "AUTHENTICATION", 3),
                (RateLimitError, 429, "RATE_LIMIT", 3),
                (InternalServerError, 500, "SERVER_ERROR", 6)):
            with self.subTest(exception=exception_type.__name__):
                response = httpx2.Response(http_status, request=request,
                                           headers={"x-request-id": "req_offline"})
                body = {"error": {"type": "invalid_request_error", "code": "invalid_schema",
                                  "param": "text.format", "message": "secret must not persist"}}
                error = exception_type("secret must not persist", response=response, body=body)
                result, parents, attempts, cache_count, budget, sdk_calls = self.run_offline(
                    lambda _: (_ for _ in ()).throw(error))
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(len(sdk_calls), calls)
                self.assertEqual(len(attempts), calls)
                self.assertEqual(budget, calls)
                self.assertEqual(cache_count, 0)
                self.assertTrue(all(a["failure_stage"] == stage and a["http_status"] == http_status
                                    and a["request_id"] == "req_offline" and
                                    a["api_error_code"] == "invalid_schema" and
                                    a["api_error_type"] == "invalid_request_error" and
                                    a["api_error_param"] == "text.format" and
                                    a["token_usage"]["total_tokens"] is None for a in attempts))
                self.assertNotIn("secret must not persist", json.dumps(attempts))
                self.assertTrue(all(len(p["attempt_refs"]) == calls // 3 for p in parents.values()))

    def test_connection_timeout_and_unknown_value_error(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for error, stage in ((APIConnectionError(message="private connection detail", request=request), "CONNECTION"),
                             (APITimeoutError(request=request), "TIMEOUT"),
                             (ValueError("sk-proj-synthetic-secret C:\\private\\key"), "UNKNOWN")):
            with self.subTest(stage=stage):
                result, _, attempts, cache_count, budget, _ = self.run_offline(
                    lambda _: (_ for _ in ()).throw(error))
                self.assertEqual(result["api_calls"], 6)
                self.assertEqual(budget, 6)
                self.assertEqual(cache_count, 0)
                self.assertTrue(all(a["failure_stage"] == stage and a["retry_decision"] ==
                                    ("RETRY" if a["attempt"] == 1 else "STOP") for a in attempts))
                self.assertNotIn("synthetic-secret", json.dumps(attempts))
                self.assertNotIn("private connection detail", json.dumps(attempts))
                if stage == "UNKNOWN":
                    self.assertTrue(all("fingerprint" in a["sanitized_error"] for a in attempts))

    def test_request_build_and_unexpected_sdk_stage(self):
        record = synthetic_record()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-only"}):
            root = Path(directory)
            client = MockClient(lambda name: mock_response(name, record["snapshot_id"]))
            team = LegacyAgentTeam(root, client_factory=lambda: client)
            original = team._request_args
            calls = [0]
            def fail_after_preflight(name, wire):
                calls[0] += 1
                if calls[0] > 3:
                    raise ValueError("offline construction failure")
                return original(name, wire)
            with patch.object(team, "_request_args", side_effect=fail_after_preflight):
                result = team.run(record)
            attempts = [json.loads(path.read_text(encoding="utf-8"))
                        for path in (root / "attempts").glob("*.json")]
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(len(client.calls), 0)
            self.assertEqual(len(attempts), 6)
            self.assertTrue(all(a["failure_stage"] == "REQUEST_BUILD" and not a["sdk_attempted"]
                                for a in attempts))

        result, _, attempts, _, budget, _ = self.run_offline(
            lambda _: (_ for _ in ()).throw(RuntimeError("private unexpected SDK detail")))
        self.assertEqual(result["api_calls"], 3)
        self.assertEqual(budget, 3)
        self.assertTrue(all(a["failure_stage"] == "SDK_CALL" for a in attempts))
        self.assertNotIn("private unexpected SDK detail", json.dumps(attempts))

    def test_sdk_response_validation_error_is_separate(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        response = httpx2.Response(200, request=request, headers={"x-request-id": "req_validation"})
        error = APIResponseValidationError(response,
                                           body={"usage": {"input_tokens": 10, "output_tokens": 5,
                                                           "total_tokens": 15}},
                                           message="secret in SDK error")
        result, _, attempts, cache_count, budget, _ = self.run_offline(
            lambda _: (_ for _ in ()).throw(error))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(budget, 3)
        self.assertEqual(cache_count, 0)
        self.assertTrue(all(a["failure_stage"] == "API_RESPONSE_VALIDATION" and
                            a["http_status"] == 200 and a["request_id"] == "req_validation" and
                            a["token_usage"]["total_tokens"] == 15 for a in attempts))
        self.assertNotIn("secret in SDK error", json.dumps(attempts))

    def test_all_roles_successful_mock_response_to_cache(self):
        record = synthetic_record()
        result, parents, attempts, cache_count, budget, sdk_calls = self.run_offline(
            lambda name: mock_response(name, record["snapshot_id"]))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(cache_count, 3)
        self.assertEqual(budget, 3)
        self.assertEqual(len(attempts), 3)
        self.assertTrue(all(a["status"] == "SUCCESS" and a["failure_stage"] is None and
                            a["response_id"] == "resp_offline" and a["request_id"] == "req_offline" and
                            a["token_usage"]["total_tokens"] == 170 for a in attempts))
        self.assertTrue(all(p["cache_status"] == "STORED" and p["token_usage"]["total_tokens"] == 170
                            and len(p["attempt_refs"]) == 1 for p in parents.values()))
        self.assertTrue(all(call["tools"] == [] and call["tool_choice"] == "none" and
                            call["max_output_tokens"] == 1600 for call in sdk_calls))

    def test_actual_sdk_pydantic_response_output_text_for_all_roles(self):
        record = synthetic_record()
        result, parents, attempts, cache_count, _, _ = self.run_offline(
            lambda name: sdk_response(name, record["snapshot_id"]))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(cache_count, 3)
        self.assertTrue(all(a["output_item_types"] == ["message", "output_text"] and
                            a["token_usage"]["total_tokens"] == 170 for a in attempts))
        self.assertTrue(all(p["cache_status"] == "STORED" for p in parents.values()))

    def test_successful_retry_clears_parent_failure_but_preserves_attempt(self):
        record = synthetic_record()
        counts = {"bull": 0, "bear": 0, "risk": 0}
        def response(name):
            counts[name] += 1
            if counts[name] == 1:
                return mock_response(name, record["snapshot_id"], status="incomplete",
                                     incomplete_reason="max_output_tokens")
            return mock_response(name, record["snapshot_id"])
        result, parents, attempts, cache_count, budget, _ = self.run_offline(response)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(budget, 6)
        self.assertEqual(cache_count, 3)
        self.assertEqual(len(attempts), 6)
        self.assertTrue(all(p["failure_stage"] is None and p["error_class"] is None and
                            p["retry_count"] == 1 and len(p["attempt_refs"]) == 2 for p in parents.values()))
        self.assertTrue(all(a["failure_stage"] == "OUTPUT_TRUNCATED" for a in attempts if a["attempt"] == 1))

    def test_parse_schema_claim_and_numeric_failures_preserve_failed_usage(self):
        record = synthetic_record()
        digest = record["snapshot_id"]
        def bad_schema(name):
            return {"agent_type": name}
        def bad_claim(name):
            report = valid_report(name, digest)
            field = "risk_factors" if name == "risk" else "key_factors"
            report[field][0]["evidence_ids"] = ["unknown.reference"]
            return report
        def bad_number(name):
            report = valid_report(name, digest)
            field = "risk_factors" if name == "risk" else "key_factors"
            report[field][0]["text"] = "Revenue grew 40%."
            report[field][0]["claim_type"] = "NUMERICAL_FACT"
            report[field][0]["support_type"] = "DIRECT"
            return report
        for make, stage in ((lambda name: mock_response(name, digest, text="{not-json"), "STRUCTURED_PARSE"),
                            (lambda name: mock_response(name, digest, report=bad_schema(name)), "SCHEMA_VALIDATION"),
                            (lambda name: mock_response(name, digest, report=bad_claim(name)), "CLAIM_VALIDATION"),
                            (lambda name: mock_response(name, digest, report=bad_number(name)), "NUMERICAL_GROUNDING")):
            with self.subTest(stage=stage):
                result, parents, attempts, cache_count, _, _ = self.run_offline(make)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["api_calls"], 6)
                self.assertEqual(cache_count, 0)
                self.assertTrue(all(a["failure_stage"] == stage and a["token_usage"]["total_tokens"] == 170
                                    for a in attempts))
                self.assertTrue(all(p["token_usage"]["total_tokens"] == 340 for p in parents.values()))

    def test_refusal_incomplete_failed_and_empty_response(self):
        record = synthetic_record()
        digest = record["snapshot_id"]
        for make, stage in ((lambda name: mock_response(name, digest, content_type="refusal"), "RESPONSE_REFUSAL"),
                            (lambda name: mock_response(name, digest, status="incomplete",
                                                        incomplete_reason="max_output_tokens"), "OUTPUT_TRUNCATED"),
                            (lambda name: mock_response(name, digest, status="failed"), "RESPONSE_STATUS"),
                            (lambda name: mock_response(name, digest, text=" "), "RESPONSE_EMPTY")):
            with self.subTest(stage=stage):
                result, _, attempts, cache_count, _, _ = self.run_offline(make)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(cache_count, 0)
                self.assertTrue(all(a["failure_stage"] == stage and a["response_status"] is not None and
                                    a["token_usage"]["total_tokens"] == 170 for a in attempts))
                if stage == "OUTPUT_TRUNCATED":
                    self.assertTrue(all(a["completion_reason"] == "max_output_tokens" for a in attempts))

    def test_attempt_ledger_failure_blocks_sdk_and_cache_stage_is_explicit(self):
        record = synthetic_record()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-only"}):
            client = MockClient(lambda name: mock_response(name, record["snapshot_id"]))
            team = LegacyAgentTeam(Path(directory), client_factory=lambda: client)
            with patch.object(team, "_attempt_ledger", side_effect=OSError("private disk path")):
                with self.assertRaises(AgentError) as failure:
                    team.run(record)
            self.assertEqual(failure.exception.code, "LEDGER_UNAVAILABLE")
            self.assertEqual(failure.exception.stage, FailureStage.LEDGER_COMMIT)
            self.assertEqual(len(client.calls), 0)
            self.assertEqual(team.usage.totals("openai_agents")[0], 1)
            self.assertFalse((Path(directory) / "cache").exists())

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-only"}):
            root = Path(directory)
            client = MockClient(lambda name: mock_response(name, record["snapshot_id"]))
            team = LegacyAgentTeam(root, client_factory=lambda: client)
            original = agent_research._atomic_json
            def fail_cache(path, value):
                if path.parent.name == "cache":
                    raise OSError("private disk path")
                original(path, value)
            with patch.object(agent_research, "_atomic_json", side_effect=fail_cache):
                result = team.run(record)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue(all(json.loads(path.read_text(encoding="utf-8"))["cache_error_stage"] == "CACHE_WRITE"
                                for path in (root / "runs").glob("*.json")))
            self.assertEqual(len(list((root / "cache").glob("*.json"))), 0)


if __name__ == "__main__":
    unittest.main()
