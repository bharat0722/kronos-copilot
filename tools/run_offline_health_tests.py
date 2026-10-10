"""Run product regressions with external networking blocked (no research targets)."""
from __future__ import annotations

import json
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app"), str(ROOT / "src")]
MODULES = (
    "test_market_data_service", "test_product_pipeline", "test_phase3",
    "test_news_intelligence", "test_news_impact", "test_phase6_3_hardening",
    "test_phase7_agents", "test_phase7_2a_diagnostics", "test_phase7_2c_evidence_ids",
    "test_phase7_2e_numeric_grounding", "test_phase7_2f1_bull_only",
    "test_phase7_3a_claim_traceability", "test_phase7_3b_agent_output_v2",
    "test_phase8_evidence_fusion", "test_health_remediation", "test_claim_contract_repair",
    "test_fixture_serialization_repair",
    "test_structured_claim_repair",
    "test_agent_output_v3",
    "test_v3_typed_prose",
    "test_agent_output_v4",
    "test_final_role_use_repair",
)

def main():
    original = socket.socket.connect
    blocked = []
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            blocked.append(str(address[0]))
            raise RuntimeError("External network prohibited in offline health tests")
        return original(sock, address)
    resolver = socket.getaddrinfo
    def local_resolve(host, *args, **kwargs):
        if host not in {None, "127.0.0.1", "::1", "localhost"}:
            blocked.append(str(host))
            raise RuntimeError("External DNS prohibited in offline health tests")
        return resolver(host, *args, **kwargs)
    with patch.object(socket.socket, "connect", local_only), patch.object(socket, "getaddrinfo", local_resolve), \
            patch.dict(os.environ, {"KRONOS_LIVE_YAHOO_REGRESSION": "0"}):
        suite = unittest.defaultTestLoader.loadTestsFromNames(
            ["research.tests." + name for name in MODULES])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {"run": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
               "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
               "blocked_external_attempts": len(blocked), "external_calls": 0}
    summary["failure_details"] = [(str(test), detail) for test, detail in result.failures + result.errors]
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "offline_health_test_result.json"
    target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() and not blocked else 1

if __name__ == "__main__":
    raise SystemExit(main())
