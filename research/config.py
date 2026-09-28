"""Research configuration defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = PROJECT_ROOT / "research"
RESULTS_DIR = RESEARCH_ROOT / "results"
REPORTS_DIR = RESULTS_DIR / "reports"
RUNS_DIR = RESULTS_DIR / "runs"
ARTIFACTS_DIR = RESULTS_DIR / "artifacts"
LOGS_DIR = RESULTS_DIR / "logs"
REGISTRY_PATH = RESULTS_DIR / "experiments.sqlite3"
DATASET_DIR = RESEARCH_ROOT / "data"

BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["amount"]
DEFAULT_SYSTEM_CONFIGURATION_ID = "kronos_only_v1"
SCHEMA_VERSION = 2
DATASET_MANIFEST_VERSION = "phase1a2_dataset_manifest_v1"
QUALITY_REPORT_VERSION = "phase1a2_quality_v1"
PREPROCESSING_VERSION = "phase1-preprocessing-v1"
METRICS_VERSION = "phase1a2_metrics_v1"
REGIME_VERSION = "phase1a2_regimes_v1"
BENCHMARK_PROFILE_VERSION = "phase1a2_profiles_v1"
MINIMUM_RESEARCH_N = 5
BOOTSTRAP_RESAMPLES = 300
BOOTSTRAP_CONFIDENCE = 0.95


@dataclass(frozen=True)
class SamplingConfig:
    temperature: float = 1.0
    top_k: int = 0
    top_p: float = 0.9
    sample_count: int = 1


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    symbols: tuple[str, ...]
    horizons: tuple[int, ...] = (24,)
    lookback_bars: int = 400
    stride_bars: int = 24
    session_policy: str = "cross_session_allowed"
    max_windows_per_symbol: int = 2
    system_configuration_id: str = DEFAULT_SYSTEM_CONFIGURATION_ID
    sampling: SamplingConfig = field(default_factory=SamplingConfig)


def ensure_research_dirs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
