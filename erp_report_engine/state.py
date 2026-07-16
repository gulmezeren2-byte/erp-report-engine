"""Run-state store: a small SQLite file that gives the engine memory.

Keeps every run's KPI snapshot so the report can say "third consecutive
decline" instead of only "down vs last week" - trend memory beyond the
lookback window, without re-querying the ERP.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3


class State:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS runs ("
            " run_at TEXT, week TEXT, kpis_json TEXT, report_path TEXT)"
        )
        self.conn.commit()

    def record(self, week: str, kpis: dict, report_path: str) -> None:
        slim = {k: v for k, v in kpis.items() if not k.startswith("_") and k != "trend"}
        self.conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?)",
            (dt.datetime.now().isoformat(timespec="seconds"), week, json.dumps(slim), report_path),
        )
        self.conn.commit()

    def streak(self, metric: str = "revenue") -> int:
        """Consecutive weekly declines of a metric across recorded runs (latest first)."""
        rows = self.conn.execute(
            "SELECT week, kpis_json FROM runs ORDER BY run_at DESC LIMIT 12"
        ).fetchall()
        seen, values = set(), []
        for week, blob in rows:
            if week in seen:
                continue
            seen.add(week)
            try:
                values.append(json.loads(blob)[metric]["now"])
            except Exception:
                break
        streak = 0
        for a, b in zip(values, values[1:], strict=False):
            if a < b:
                streak += 1
            else:
                break
        return streak

    def close(self) -> None:
        self.conn.close()
