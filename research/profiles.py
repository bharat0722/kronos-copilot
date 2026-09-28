"""Benchmark profiles. Full profiles are defined but never auto-launched."""

from __future__ import annotations

from .config import BenchmarkProfile


PROFILES = {
    "dry-run": BenchmarkProfile(name="dry-run", symbols=("SYNTH",), horizons=(24,), max_windows_per_symbol=1),
    "smoke": BenchmarkProfile(name="smoke", symbols=("SYNTH",), horizons=(24,), max_windows_per_symbol=2),
    "quick": BenchmarkProfile(name="quick", symbols=("SYNTH",), horizons=(24, 75), stride_bars=75, max_windows_per_symbol=3),
    "standard": BenchmarkProfile(name="standard", symbols=("RELIANCE.NS", "TCS.NS", "INFY.NS"), horizons=(24, 75), stride_bars=75, max_windows_per_symbol=10),
    "full": BenchmarkProfile(name="full", symbols=(), horizons=(24, 75, 120), stride_bars=75, max_windows_per_symbol=0),
    "locked_test": BenchmarkProfile(name="locked_test", symbols=(), horizons=(24, 75, 120), stride_bars=120, max_windows_per_symbol=0),
}


def get_profile(name: str) -> BenchmarkProfile:
    try:
        return PROFILES[name]
    except KeyError as error:
        raise ValueError(f"Unknown profile: {name}. Choose one of: {', '.join(PROFILES)}") from error
