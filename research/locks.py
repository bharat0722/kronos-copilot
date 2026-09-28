"""Small local file lock for Kronos inference safety across processes."""

from __future__ import annotations

import os
import time
from pathlib import Path

from .config import RESULTS_DIR


class ForecastLock:
    def __init__(self, owner: str, timeout_seconds: float = 2.0, stale_seconds: float = 3600.0):
        self.owner = owner
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self.path = RESULTS_DIR / "kronos_inference.lock"
        self.acquired = False

    def __enter__(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"{self.owner}\n{os.getpid()}\n{time.time()}\n")
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_seconds:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() >= deadline:
                    raise RuntimeError("Kronos inference is already running in another local process.")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            self.path.unlink(missing_ok=True)
        self.acquired = False
