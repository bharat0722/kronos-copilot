"""Small local Bronze/Silver/Gold observer for product market data.

It records existing provider and forecast outputs; it never selects data or
changes the forecast path. Raw/provider artifacts stay server-side.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_data import ProviderResult
from research.technical_intelligence import analyze


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _stage(status: str, *, rows: int | None = None, updated: str | None = None,
           latency_ms: int | None = None, warnings: list[str] | None = None,
           errors: list[str] | None = None, provider: str | None = None,
           cache_status: str = "not_applicable") -> dict[str, Any]:
    return {"status": status, "rows": rows, "last_update": updated,
            "latency_ms": latency_ms, "warnings": warnings or [], "errors": errors or [],
            "provider": provider, "cache_status": cache_status}


class ProductPipeline:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()
        self._latest = root / "latest.json"

    def _immutable(self, folder: str, content: bytes, suffix: str) -> dict[str, Any]:
        digest = _sha(content)
        path = self.root / folder / f"{digest}.{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            pass
        return {"sha256": digest, "path": str(path.relative_to(self.root)), "bytes": len(content)}

    def _write_latest(self, manifest: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f"latest.{threading.get_ident()}.tmp"
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
        os.replace(temporary, self._latest)

    def capture(self, result: ProviderResult) -> str:
        started = time.monotonic()
        retrieved = str(result.provenance.get("retrieved_at") or _now())
        symbol = str(result.provenance.get("source_symbol") or result.request.canonical().provider_symbols.get("yahoo"))
        cache_status = "hit" if result.provenance.get("cache_hit") else "miss"
        native = result.raw_payload
        bronze = self._immutable("bronze", native.encode("utf-8"), "csv") if native else None
        canonical = result.bars.to_csv(index=False).encode("utf-8")
        silver = self._immutable("silver", canonical, "csv")
        quality = result.quality
        issue_names = [str(issue.get("code", "QUALITY_WARNING")) for issue in quality.get("issues", [])]
        quality_state = quality.get("state", "FAIL")
        if quality_state not in {"PASS", "WARN", "FAIL"}:
            quality_state = "FAIL"
        capture_id = _sha((symbol + retrieved + silver["sha256"]).encode("utf-8"))
        stages = {
            "source": _stage(result.health.get("status", "DEGRADED"), rows=len(result.bars),
                             updated=retrieved, latency_ms=result.health.get("latency_ms"),
                             provider=result.provider, cache_status=cache_status),
            "bronze": _stage("HEALTHY" if bronze else "DEGRADED", rows=len(result.bars), updated=retrieved,
                             warnings=[] if bronze else ["Provider-native payload unavailable"],
                             provider=result.provider, cache_status=cache_status),
            "silver": _stage({"PASS": "HEALTHY", "WARN": "DEGRADED", "FAIL": "FAILED"}[quality_state],
                             rows=len(result.bars), updated=retrieved, warnings=issue_names if quality_state == "WARN" else [],
                             errors=issue_names if quality_state == "FAIL" else [], provider=result.provider,
                             cache_status=cache_status),
            "gold": _stage("STALE", warnings=["Awaiting a matching forecast"], provider=result.provider),
            "intelligence": _stage("STALE", warnings=["Awaiting a matching forecast"], provider=result.provider),
        }
        manifest = {"schema_version": "capstone_pipeline_v1", "capture_id": capture_id,
                    "symbol": symbol, "interval": result.request.interval, "provider": result.provider,
                    "retrieved_at": retrieved, "bronze": bronze, "silver": silver,
                    "quality": quality, "provenance": result.provenance, "stages": stages,
                    "updated_at": _now()}
        manifest["stages"]["bronze"]["latency_ms"] = int((time.monotonic() - started) * 1000)
        with self._lock:
            self._write_latest(manifest)
        return capture_id

    def complete(self, capture_id: str, context: pd.DataFrame, payload: dict[str, Any], *,
                 validation: bool = False) -> None:
        started = time.monotonic()
        with self._lock:
            if not self._latest.is_file():
                return
            manifest = json.loads(self._latest.read_text(encoding="utf-8"))
            if manifest.get("capture_id") != capture_id:
                return
            normalized = context.rename(columns={"timestamps": "timestamp"}).tail(400).copy()
            indicators = analyze(normalized)
            indicators["analysis_version"] = "phase3_technical_intelligence@" + _sha(
                (Path(__file__).resolve().parents[1] / "research" / "technical_intelligence.py").read_bytes()
            )
            context_bytes = normalized.to_csv(index=False).encode("utf-8")
            forecast = payload.get("chart", {}).get("forecast", [])
            forecast_hash = _sha(json.dumps(forecast, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            gold = {
                "context": {"rows": len(normalized), "sha256": _sha(context_bytes),
                            "last_timestamp": str(normalized["timestamp"].iloc[-1]), "validation_context": validation},
                "technicals": indicators,
                "kronos_output": {"forecast_bars": len(forecast), "sha256": forecast_hash,
                                  "summary_fingerprint": payload.get("summary_fingerprint"),
                                  "model": payload.get("model"), "cache_hit": bool(payload.get("cache_hit"))},
                "ensemble_output": {"status": "RESEARCH_ONLY", "reason":
                    "Frozen Phase 3 weights were fit to a different Kronos configuration; no live ensemble is applied."},
                "evidence": [{"type": "technical", "name": item["indicator"], "signal": item["signal"],
                              "strength": item["strength"], "reason": item["reason"],
                              "as_of": indicators["as_of"]} for item in indicators["indicators"]],
            }
            gold_bytes = json.dumps(gold, sort_keys=True, default=str).encode("utf-8")
            manifest["gold"] = self._immutable("gold", gold_bytes, "json")
            updated = _now()
            manifest["stages"]["gold"] = _stage("HEALTHY", rows=len(normalized), updated=updated,
                                                   latency_ms=int((time.monotonic() - started) * 1000),
                                                   provider=manifest["provider"],
                                                   cache_status="hit" if payload.get("cache_hit") else "miss")
            manifest["stages"]["intelligence"] = _stage("DEGRADED", rows=len(forecast), updated=updated,
                   warnings=["Ensemble remains research-only"],
                   provider="local Kronos + deterministic technicals",
                   cache_status="hit" if payload.get("cache_hit") else "miss")
            manifest["updated_at"] = updated
            self._write_latest(manifest)

    def record_error(self, message: str) -> None:
        with self._lock:
            manifest = json.loads(self._latest.read_text(encoding="utf-8")) if self._latest.exists() else {
                "schema_version": "capstone_pipeline_v1", "stages": {}}
            manifest["stages"]["gold"] = _stage("FAILED", updated=_now(), errors=[message])
            manifest["updated_at"] = _now()
            self._write_latest(manifest)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if not self._latest.is_file():
                return {"schema_version": "capstone_pipeline_v1", "symbol": None, "updated_at": None,
                        "stages": {name: _stage("STALE", warnings=["No local capture yet"])
                                   for name in ("source", "bronze", "silver", "gold", "intelligence")}}
            manifest = json.loads(self._latest.read_text(encoding="utf-8"))
        stages = manifest["stages"]
        updated = pd.Timestamp(manifest["updated_at"])
        if (pd.Timestamp.now(tz="UTC") - updated).total_seconds() > 3600:
            stages = {name: {**stage, "status": "STALE" if stage["status"] == "HEALTHY" else stage["status"]}
                      for name, stage in stages.items()}
        return {"schema_version": manifest["schema_version"], "symbol": manifest.get("symbol"),
                "interval": manifest.get("interval"), "updated_at": manifest.get("updated_at"),
                "stages": stages}

    def matching_technicals(self, symbol: str, fingerprint: str) -> dict[str, Any] | None:
        """Read Gold technicals only when they belong to this exact saved forecast."""
        try:
            with self._lock:
                manifest = json.loads(self._latest.read_text(encoding="utf-8"))
                if manifest.get("symbol") != symbol:
                    return None
                gold_ref = manifest["gold"]
                path = (self.root / gold_ref["path"]).resolve()
                if not path.is_relative_to(self.root.resolve()):
                    return None
                content = path.read_bytes()
            if _sha(content) != gold_ref["sha256"]:
                return None
            gold = json.loads(content)
            return gold["technicals"] if gold["kronos_output"]["summary_fingerprint"] == fingerprint else None
        except (OSError, ValueError, KeyError, TypeError):
            return None
