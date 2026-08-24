"""Local Ox Alpha deep-audit utility for Kronos Copilot.

This tool collects safe project context, excludes secrets and large artifacts,
asks OpenRouter Ox Alpha for an architecture/code audit, and saves the report.
It does not modify the forecasting pipeline or dashboard.
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "docs" / "ox_alpha_audit.md"
MODEL = "stealth/ox-alpha"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
IST = ZoneInfo("Asia/Kolkata")

INCLUDE_FILES = [
    "README.md",
    "requirements.txt",
    "Start Kronos Copilot.bat",
    "app/server.py",
    "app/dashboard.html",
    "app/dashboard.css",
    "app/dashboard.js",
    "src/forecast_config.py",
    "src/first_forecast.py",
    "outputs/forecast_summary.json",
    "vendor/Kronos-master/README.md",
    "vendor/Kronos-master/model/kronos.py",
    "vendor/Kronos-master/model/module.py",
    "vendor/Kronos-master/examples/prediction_example.py",
    "vendor/Kronos-master/examples/prediction_batch_example.py",
    "vendor/Kronos-master/examples/run_backtest_kronos.py",
    "vendor/Kronos-master/tests/test_kronos_regression.py",
    "vendor/Kronos-master/finetune_csv/README.md",
    "vendor/Kronos-master/finetune_csv/finetune_base_model.py",
    "vendor/Kronos-master/finetune_csv/finetune_tokenizer.py",
    "vendor/Kronos-master/finetune/train_predictor.py",
    "vendor/Kronos-master/finetune/train_tokenizer.py",
]

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "forecast_cache",
    "node_modules",
    "pdf_qa",
}
FORBIDDEN_EXTS = {
    ".bin",
    ".ckpt",
    ".db",
    ".docx",
    ".exe",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pt",
    ".pth",
    ".safetensors",
    ".sqlite",
    ".zip",
}
MAX_FILE_CHARS = 180_000

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*['\"]?([^\s'\",}]+)"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-or-[A-Za-z0-9_\-]{16,}"),
]

MASTER_PROMPT = """
You are Ox Alpha performing a deep local architecture and quality audit of an
existing project called Kronos Copilot.

Project purpose:
- India-first financial forecasting dashboard.
- Yahoo Finance/yfinance supplies recent five-minute NSE/BSE market bars.
- Kronos-base runs locally and produces forecasts.
- OpenAI is optional and only explains an already completed Kronos forecast.
- GPT/OpenAI must not generate or change forecast values.

Audit requirements:
A. Explain the architecture top to bottom in simple Demo Day language.
B. Verify the separation between Yahoo data, Kronos forecasting, and AI explanation.
C. Review backend API boundaries, startup, LAN/local behavior, and key handling.
D. Review ticker/company search and NSE/BSE symbol normalization.
E. Review forecast horizon, trading-session timestamps, chart semantics, and saved results.
F. Review frontend state integrity, stale-result protection, accessibility, and responsiveness.
G. Compare local Kronos usage against the official Kronos reference context supplied.
H. Identify security/cost/reliability risks, especially accidental API calls or secret leakage.
I. Identify performance bottlenecks and Demo Day failure modes.
J. Give concrete findings with severity, evidence, impact, and recommended fix.
K. Provide top 5 next actions, but do not suggest replacing the current MVP architecture.

Output format:
1. Executive summary
2. Current architecture explained simply
3. What works well
4. Findings table with severity, evidence, impact, recommendation
5. Kronos usage review
6. Data and timestamp review
7. Frontend/dashboard review
8. Security and API-cost review
9. Demo Day readiness review
10. Top 5 next actions
"""


def rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def load_openrouter_key() -> str:
    env_path = PROJECT_ROOT / ".env.local"
    if not env_path.exists():
        raise RuntimeError(".env.local was not found.")
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "OPENROUTER_API_KEY":
            key = value.strip().strip("'\"")
            if key:
                return key
    raise RuntimeError("OPENROUTER_API_KEY was not found in .env.local.")


def is_forbidden(path: Path) -> bool:
    parts = set(path.relative_to(PROJECT_ROOT).parts)
    name = path.name.lower()
    if parts & FORBIDDEN_PARTS:
        return True
    if name == ".env" or name == ".env.local" or name.startswith(".env."):
        return True
    if path.suffix.lower() in FORBIDDEN_EXTS:
        return True
    rel_path = rel(path)
    if rel_path.startswith("data/"):
        return True
    if rel_path.startswith("outputs/") and rel_path != "outputs/forecast_summary.json":
        return True
    return False


def redact_secrets(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        if match.lastindex and match.lastindex >= 2:
            return match.group(0).replace(match.group(2), "[REDACTED]")
        return "[REDACTED]"

    for pattern in SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def safe_text(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, "missing"
    if is_forbidden(path):
        return None, "forbidden"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return None, f"read_error:{exc.__class__.__name__}"
    text = redact_secrets(text)
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n\n[TRUNCATED FOR AUDIT CONTEXT]\n"
    return text, None


def detect_structure() -> str:
    important = []
    for path in PROJECT_ROOT.rglob("*"):
        if path.is_file() and not is_forbidden(path):
            rp = rel(path)
            if rp.startswith(("app/", "src/")) or rp in {"README.md", "requirements.txt"}:
                important.append(rp)
    return "\n".join(f"- {item}" for item in sorted(important)[:250])


def collect_context() -> tuple[str, dict[str, object]]:
    included: list[dict[str, object]] = []
    excluded: list[dict[str, str]] = []
    sections = [
        "# Kronos Copilot Safe Audit Context",
        "## 1. Project Overview",
        detect_structure(),
        "## 2. Known Current Results",
        textwrap.dedent(
            """
            - Forecast horizon was upgraded from 24 five-minute bars to 75 five-minute market bars.
            - 75 bars represent 6 hours 15 minutes of Indian trading time.
            - The dashboard labels closed-market hours as omitted in trading-time view.
            - Forecast examples may include date rollovers; the chart should not show overnight continuity.
            - Existing behavior keeps GPT/OpenAI explanation optional and cache-first.
            """
        ).strip(),
    ]

    buckets = {
        "Backend": ["app/server.py"],
        "Forecast Engine": ["src/forecast_config.py", "src/first_forecast.py"],
        "Frontend": ["app/dashboard.html", "app/dashboard.css", "app/dashboard.js"],
        "Validation And Saved Result": ["outputs/forecast_summary.json"],
        "Official Kronos Reference": [p for p in INCLUDE_FILES if p.startswith("vendor/Kronos-master/")],
        "Project Docs And Startup": ["README.md", "requirements.txt", "Start Kronos Copilot.bat"],
    }

    for title, paths in buckets.items():
        sections.append(f"## {title}")
        for item in paths:
            path = PROJECT_ROOT / item
            text, reason = safe_text(path)
            if text is None:
                excluded.append({"path": item, "reason": reason or "unknown"})
                continue
            included.append({"path": item, "chars": len(text)})
            sections.append(f"### File: {item}\n```text\n{text}\n```")

    context = "\n\n".join(sections)
    approx_tokens = max(1, len(context) // 4)
    stats = {
        "included_files": included,
        "excluded_files": excluded,
        "included_count": len(included),
        "excluded_count": len(excluded),
        "chars": len(context),
        "approx_tokens": approx_tokens,
        "largest_files": sorted(included, key=lambda x: int(x["chars"]), reverse=True)[:5],
    }
    return context, stats


def assert_no_secret_leak(text: str) -> None:
    actual_key = ""
    try:
        actual_key = load_openrouter_key()
    except RuntimeError:
        pass
    if actual_key and actual_key in text:
        raise RuntimeError("The actual OpenRouter key was found in outgoing or saved text.")
    blocked_names = ["Authorization: Bearer " + actual_key] if actual_key else []
    for value in blocked_names:
        if value in text:
            raise RuntimeError(f"Secret-sensitive marker found in outgoing or saved text: {value}")
    for pattern in SECRET_PATTERNS[1:]:
        if pattern.search(text):
            raise RuntimeError("Secret-like value found in outgoing or saved text.")


def call_ox_alpha(context: str) -> dict[str, object]:
    key = load_openrouter_key()
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"{context}\n\n# Audit Instructions\n{MASTER_PROMPT}",
            }
        ],
        "temperature": 0.2,
        "max_tokens": 14000,
        "reasoning": {"effort": "medium"},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8000",
            "X-Title": "Kronos Copilot Ox Alpha Audit",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            status = response.status
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1000]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc

    choice = data.get("choices", [{}])[0]
    message = choice.get("message") or {}
    report = message.get("content") or ""
    if not report.strip():
        raise RuntimeError("Ox Alpha returned an empty report.")
    usage = data.get("usage") or {}
    return {
        "status": status,
        "finish_reason": choice.get("finish_reason"),
        "report": report,
        "usage": usage,
    }


def save_report(report: str, stats: dict[str, object], meta: dict[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    supplied = "\n".join(f"- {item['path']} ({item['chars']} chars)" for item in stats["included_files"])
    header = f"""---
model: {MODEL}
audit_datetime_ist: {meta["audit_datetime_ist"]}
files_supplied: {stats["included_count"]}
approx_context_tokens: {stats["approx_tokens"]}
request_tokens: {meta.get("prompt_tokens", "unknown")}
completion_tokens: {meta.get("completion_tokens", "unknown")}
total_tokens: {meta.get("total_tokens", "unknown")}
cost: {meta.get("cost", "unknown")}
finish_reason: {meta.get("finish_reason", "unknown")}
---

# Ox Alpha Deep Audit - Kronos Copilot

## Files Supplied
{supplied}

## Audit Report
"""
    output = header + "\n" + report.strip() + "\n"
    assert_no_secret_leak(output)
    REPORT_PATH.write_text(output, encoding="utf-8")


def dashboard_still_runs() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/dashboard", timeout=8) as response:
            return response.status == 200
    except Exception:
        return False


def main() -> int:
    context, stats = collect_context()
    assert_no_secret_leak(context)
    print(json.dumps({"safe_context_stats": stats}, indent=2), flush=True)

    result = call_ox_alpha(context)
    usage = result.get("usage", {}) or {}
    meta = {
        "audit_datetime_ist": datetime.now(IST).isoformat(timespec="seconds"),
        "finish_reason": result.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost": usage.get("cost"),
    }
    save_report(str(result["report"]), stats, meta)

    report_text = REPORT_PATH.read_text(encoding="utf-8")
    report_has_findings = bool(re.search(r"(?i)(finding|severity|recommendation|next action)", report_text))
    print(
        json.dumps(
            {
                "model": MODEL,
                "http_status": result.get("status"),
                "finish_reason": result.get("finish_reason"),
                "usage": usage,
                "report_path": str(REPORT_PATH),
                "report_chars": len(report_text),
                "report_has_concrete_findings": report_has_findings,
                "checks": {
                    "env_local_excluded": ".env.local" not in context and ".env.local" not in report_text,
                    "api_key_absent": not any(pattern.search(report_text) for pattern in SECRET_PATTERNS),
                    "model_weights_excluded": not any(
                        str(item.get("path", "")).lower().endswith((".safetensors", ".bin", ".pt", ".pth", ".ckpt"))
                        for item in stats["included_files"]
                    ),
                    "dashboard_still_runs": dashboard_still_runs(),
                },
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
