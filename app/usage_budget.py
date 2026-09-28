"""Atomic, process-restart-safe daily provider call counters."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class DailyUsageBudget:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("create table if not exists usage (day text not null, provider text not null, "
                       "requests integer not null, credits integer not null, primary key(day, provider))")

    def totals(self, provider: str, day: str | None = None) -> tuple[int, int]:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            row = db.execute("select requests, credits from usage where day=? and provider=?",
                             (day, provider)).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def reserve(self, provider: str, limit: int, day: str | None = None) -> bool:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("begin immediate")
            count, _ = self.totals_in(db, provider, day)
            if count >= limit:
                return False
            db.execute("insert into usage(day, provider, requests, credits) values(?,?,1,0) "
                       "on conflict(day, provider) do update set requests=requests+1", (day, provider))
            return True

    @staticmethod
    def totals_in(db: sqlite3.Connection, provider: str, day: str) -> tuple[int, int]:
        row = db.execute("select requests, credits from usage where day=? and provider=?",
                         (day, provider)).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def add_credits(self, provider: str, credits: int, day: str | None = None) -> None:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("update usage set credits=credits+? where day=? and provider=?",
                       (max(0, int(credits)), day, provider))
