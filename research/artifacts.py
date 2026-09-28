"""File-based forecast/actual path artifacts for traceability."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import RUNS_DIR


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_frame_artifact(run_id: str, experiment_id: str, artifact_type: str, frame: pd.DataFrame) -> dict[str, Any]:
    directory = RUNS_DIR / run_id / "artifacts" / experiment_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{artifact_type}.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False)
    relative = path.relative_to(RUNS_DIR.parents[0])
    return {
        "artifact_id": f"{run_id}_{experiment_id}_{artifact_type}",
        "experiment_id": experiment_id,
        "artifact_type": artifact_type,
        "relative_path": str(relative).replace("\\", "/"),
        "hash": _hash_file(path),
        "rows": int(len(frame)),
        "schema_version": "phase1a2_path_artifact_v1",
    }


def write_json_artifact(run_id: str, name: str, payload: dict[str, Any]) -> Path:
    directory = RUNS_DIR / run_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path
