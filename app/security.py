"""Small local/LAN access boundary for the capstone server."""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit


PUBLIC_ASSETS = frozenset({
    "/app/dashboard.html", "/app/dashboard.css", "/app/dashboard.js",
    "/app/professional-chart.js", "/app/vendor/lightweight-charts-5.2.1.js",
    "/app/vendor/LIGHTWEIGHT_CHARTS_LICENSE.txt",
})
EXPENSIVE_POST = frozenset({
    "/api/forecast", "/api/validation", "/api/live-forecast",
    "/api/live-validation", "/api/explanation", "/api/agents/run",
})
LOCAL_READ = frozenset({
    "/api/research/status", "/api/research/report", "/api/research/runs",
    "/api/research/experiments", "/api/research/experiment", "/api/research/failures",
})
SESSION_SECONDS = 8 * 3600


def local_secret(name: str, env_path: Path) -> str:
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, candidate = line.partition("=")
            if separator and key.strip() == name:
                return candidate.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def valid_host(host: str) -> bool:
    try:
        parsed = urlsplit(f"http://{host}")
        if (not host or parsed.path or parsed.query or parsed.fragment or
                parsed.username is not None or parsed.password is not None):
            return False
        hostname = parsed.hostname
        parsed.port  # Reject malformed ports rather than trusting their host prefix.
    except ValueError:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_private or ipaddress.ip_address(hostname).is_loopback
    except (ValueError, TypeError):
        return False


def same_origin(headers: object) -> bool:
    host = headers.get("Host", "")
    if not valid_host(host):
        return False
    if hasattr(headers, "get_all") and any(len(headers.get_all(name) or []) > 1 for name in
                                       ("Host", "Origin", "Referer", "Sec-Fetch-Site")):
        return False
    origin = headers.get("Origin")
    if origin is not None:
        try:
            parsed = urlsplit(origin)
            if (parsed.scheme != "http" or parsed.netloc != host or parsed.path or
                    parsed.query or parsed.fragment or parsed.username is not None or
                    parsed.password is not None):
                return False
        except ValueError:
            return False
    referer = headers.get("Referer")
    if referer is not None and origin is None:
        try:
            parsed = urlsplit(referer)
            if parsed.scheme != "http" or parsed.netloc != host:
                return False
        except ValueError:
            return False
    return headers.get("Sec-Fetch-Site", "same-origin") in {"same-origin", "none"}


class AccessGuard:
    def __init__(self, env_path: Path, clock=time.time):
        self.env_path = env_path
        self.clock = clock
        self._lock = threading.RLock()
        self._sessions: dict[str, float] = {}
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._daily: dict[tuple[str, str, str], int] = defaultdict(int)
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def login(self, address: str, supplied: str) -> str | None:
        expected = local_secret("KRONOS_LAN_ACCESS_CODE", self.env_path)
        if not expected or len(expected) < 12 or not hmac.compare_digest(expected, supplied):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = self.clock() + SESSION_SECONDS
        return token

    def authenticated(self, address: str, cookie: str) -> bool:
        if is_loopback(address):
            return True
        token = next((part.strip().partition("=")[2] for part in cookie.split(";")
                      if part.strip().startswith("kronos_session=")), "")
        with self._lock:
            expires = self._sessions.get(token, 0) if token else 0
            if token and expires <= self.clock():
                self._sessions.pop(token, None)
            return expires > self.clock()

    def allow(self, address: str, route: str, limit: int, seconds: int, daily: int | None = None) -> bool:
        now = self.clock()
        key = (address, route)
        day_key = (time.strftime("%Y-%m-%d", time.gmtime(now)), address, route)
        with self._lock:
            recent = self._attempts[key]
            while recent and recent[0] <= now - seconds:
                recent.popleft()
            if len(recent) >= limit or (daily is not None and self._daily[day_key] >= daily):
                self._failures[key].append(now)
                return False
            recent.append(now)
            self._daily[day_key] += 1
            return True

    def stats(self, address: str, route: str) -> dict[str, int]:
        key = (address, route)
        day_key = (time.strftime("%Y-%m-%d", time.gmtime(self.clock())), address, route)
        with self._lock:
            recent = self._attempts[key]
            while recent and recent[0] <= self.clock() - 600:
                recent.popleft()
            failures = self._failures[key]
            while failures and failures[0] <= self.clock() - 600:
                failures.popleft()
            return {"daily_count": self._daily[day_key], "recent_count": len(recent),
                    "recent_failures": len(failures)}

    def record_failure(self, address: str, route: str) -> None:
        with self._lock:
            self._failures[(address, route)].append(self.clock())
