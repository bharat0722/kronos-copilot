"""Environment, model, and seed provenance for benchmark reproducibility."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PROJECT_ROOT


def _command(args: list[str], cwd: Path = PROJECT_ROOT) -> str:
    try:
        return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def git_info(path: Path = PROJECT_ROOT) -> dict[str, object]:
    status = _command(["git", "status", "--short"], path)
    return {
        "commit": _command(["git", "rev-parse", "--short", "HEAD"], path),
        "branch": _command(["git", "branch", "--show-current"], path),
        "dirty": bool(status and status != "unknown"),
    }


def environment_info() -> dict[str, object]:
    try:
        import numpy as np
    except Exception:
        np = None
    try:
        import torch
    except Exception:
        torch = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "os": platform.system(),
        "architecture": platform.machine(),
        "pandas": pd.__version__,
        "numpy": getattr(np, "__version__", "unknown"),
        "torch": getattr(torch, "__version__", "unknown"),
        "device": "cuda" if torch is not None and getattr(torch.cuda, "is_available", lambda: False)() else "cpu",
        "cuda": getattr(getattr(torch, "version", None), "cuda", None) if torch is not None else None,
    }


def kronos_source_commit() -> str:
    vendor = PROJECT_ROOT / "vendor" / "Kronos-master"
    if not vendor.exists():
        return "unknown"
    return _command(["git", "rev-parse", "--short", "HEAD"], vendor)


def model_provenance() -> dict[str, object]:
    try:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from first_forecast import MODEL_NAME, TOKENIZER_NAME
    except Exception:
        MODEL_NAME = "unknown"
        TOKENIZER_NAME = "unknown"
    return {
        "model_family": "Kronos",
        "model_variant": "base" if "base" in str(MODEL_NAME).lower() else "unknown",
        "model_id": MODEL_NAME,
        "model_version": MODEL_NAME,
        "checkpoint_identity": MODEL_NAME,
        "model_source_repository": "https://github.com/shiyu-coder/Kronos",
        "kronos_source_commit": kronos_source_commit(),
        "tokenizer_id": TOKENIZER_NAME,
        "tokenizer_version": TOKENIZER_NAME,
        "tokenizer_checkpoint": TOKENIZER_NAME,
    }


def stable_seed(payload: dict[str, Any], base_seed: int = 20260825) -> int:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return (base_seed + int(digest[:8], 16)) % (2**31 - 1)


def apply_seed(seed: int) -> dict[str, object]:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except Exception:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass
    return {"base_seed": 20260825, "experiment_seed": seed, "determinism_level": "best_effort"}
